import argparse
import datetime
import io
import json
import logging
import os
import shutil
import re
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd
import requests

DEFAULT_BASE_URL = os.environ.get("SALESMAP_API_BASE", "https://salesmap.kr/api/v2")
DEFAULT_DB_PATH = "salesmap_latest.db"
DEFAULT_BACKUP_DIR = "backups"
DEFAULT_LOG_DIR = "logs"
DEFAULT_CHECKPOINT_DIR = "logs/checkpoints"
DEFAULT_CHECKPOINT_INTERVAL = 50
DEFAULT_KEEP_BACKUPS = 30
MIN_INTERVAL = 0.12
MAX_RETRIES = 3
BACKOFF_429 = 10.0
MAX_BACKOFF = 60.0
LOG_NAME = "salesmap"

logger = logging.getLogger(LOG_NAME)


def _load_token(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    token = os.environ.get("SALESMAP_TOKEN")
    if token:
        return token
    try:
        import streamlit as st  # type: ignore

        token = st.secrets.get("SALESMAP_TOKEN")
    except Exception:
        token = None
    return token


class SalesmapClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        min_interval: float = MIN_INTERVAL,
        max_retries: int = MAX_RETRIES,
        backoff_429: float = BACKOFF_429,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_429 = backoff_429
        self._last_request_at = 0.0

    def _respect_rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_at
        wait_for = self.min_interval - elapsed
        if wait_for > 0:
            time.sleep(wait_for)

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempts = 0
        while attempts < self.max_retries:
            self._respect_rate_limit()
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                attempts += 1
                wait = min(self.backoff_429 * attempts, MAX_BACKOFF)
                time.sleep(wait)
                continue
            self._last_request_at = time.time()
            if resp.status_code == 429:
                attempts += 1
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after)
                except Exception:
                    delay = self.backoff_429 * attempts
                time.sleep(min(delay, MAX_BACKOFF))
                continue
            if 500 <= resp.status_code < 600:
                attempts += 1
                time.sleep(min(self.backoff_429 * attempts, MAX_BACKOFF))
                continue
            if resp.ok:
                try:
                    return resp.json(), None
                except ValueError as exc:  # json decode error
                    return None, f"json_error:{exc}"
            return None, f"http_{resp.status_code}"
        return None, "max_retries_exceeded"


def sanitize_table_name(path: str) -> str:
    cleaned = path.strip("/").lower()
    cleaned = re.sub(r"[{}]", "", cleaned)
    cleaned = re.sub(r"[\\/]+", "_", cleaned)
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", cleaned)
    cleaned = re.sub(r"__+", "_", cleaned).strip("_")
    return cleaned or "table"


def _serialize_value(val: Any) -> Any:
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8")
        except Exception:
            return repr(val)
    return val


class TableWriter:
    def __init__(self, conn: sqlite3.Connection, table: str) -> None:
        self.conn = conn
        self.table = table
        self.columns: List[str] = []
        self.row_count = 0
        self.created = False

    def load_existing(self) -> None:
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (self.table,)
        )
        if cur.fetchone():
            info_cur = self.conn.execute(f'PRAGMA table_info("{self.table}")')
            self.columns = [row[1] for row in info_cur.fetchall()]
            count_cur = self.conn.execute(f'SELECT COUNT(*) FROM "{self.table}"')
            row = count_cur.fetchone()
            self.row_count = int(row[0]) if row else 0
            self.created = True

    def _ensure_table_created(self) -> None:
        if self.created:
            return
        if not self.columns:
            return
        cols_sql = ", ".join(f'"{col}" TEXT' for col in self.columns)
        self.conn.execute(f'CREATE TABLE IF NOT EXISTS "{self.table}" ({cols_sql})')
        self.created = True

    def _add_columns(self, new_columns: List[str]) -> None:
        if not new_columns:
            return
        if not self.created:
            self.columns.extend(new_columns)
            self._ensure_table_created()
            return
        for col in new_columns:
            self.conn.execute(f'ALTER TABLE "{self.table}" ADD COLUMN "{col}"')
            self.columns.append(col)

    def write_batch(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        batch_columns = collect_columns(records)
        if not self.columns:
            self.columns = batch_columns
        else:
            new_cols = [c for c in batch_columns if c not in self.columns]
            self._add_columns(new_cols)
        self._ensure_table_created()
        normalized = normalize_records(records, self.columns)
        df = pd.DataFrame(normalized, columns=self.columns)
        df.to_sql(self.table, self.conn, if_exists="append", index=False)
        self.row_count += len(records)
        return len(records)


def collect_columns(records: List[Dict[str, Any]]) -> List[str]:
    columns: List[str] = []
    for record in records:
        for key in record.keys():
            if key not in columns:
                columns.append(key)
    return columns


def collect_webform_ids(conn: sqlite3.Connection, log: logging.Logger) -> Tuple[List[str], Set[str]]:
    conn.row_factory = sqlite3.Row
    people_ids = {
        str(row[0]).strip()
        for row in conn.execute(
            'SELECT DISTINCT peopleId FROM deal WHERE peopleId IS NOT NULL AND TRIM(peopleId) <> ""'
        )
        if row[0] is not None and str(row[0]).strip()
    }
    if not people_ids:
        log.info("No peopleId found in deal table; skipping webform history collection.")
        return [], set()
    placeholders = ",".join("?" for _ in people_ids)
    query = f'SELECT id, "제출된 웹폼 목록" AS webforms FROM people WHERE id IN ({placeholders})'
    webform_ids: set[str] = set()
    try:
        for row in conn.execute(query, tuple(people_ids)):
            webform_ids.update(parse_webforms_field(row["webforms"]))
    except sqlite3.OperationalError as exc:
        if "제출된 웹폼 목록" in str(exc):
            log.info("Column '제출된 웹폼 목록' not found; skipping webform history collection.")
            return [], people_ids
        raise
    ids = sorted(webform_ids)
    log.info("Found %d unique webform IDs from deals' people set.", len(ids))
    return ids, people_ids


def fetch_webform_submissions(client: SalesmapClient, webform_id: str, log: logging.Logger) -> List[Dict[str, Any]]:
    def _extract_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Try common list keys first (webFormSubmitList appears under data)
        for key in ("items", "list", "submissions", "results", "webFormSubmitList"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                return value
        # If "data" is a dict, search within
        data_val = payload.get("data")
        if isinstance(data_val, dict):
            inner = _extract_items(data_val)
            if inner:
                return inner
        # Fallback: pick the first list value among top-level fields
        for value in payload.values():
            if isinstance(value, list) and value:
                return value
        return []

    submissions: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        params = {"cursor": cursor} if cursor else None
        data, err = client.get_json(f"webForm/{webform_id}/submit", params=params)
        if err:
            log.warning("webform %s fetch error: %s", webform_id, err)
            break
        if not data:
            break
        items = _extract_items(data)
        if not items:
            log.info("webform %s response had no items (cursor=%s)", webform_id, cursor)
            break
        for entry in items:
            if isinstance(entry, dict):
                submissions.append({**entry, "webFormId": webform_id})
        # cursor/nextCursor can appear at top-level or inside data
        next_cursor = data.get("cursor") or data.get("nextCursor")
        if not next_cursor and isinstance(data.get("data"), dict):
            next_cursor = data["data"].get("cursor") or data["data"].get("nextCursor")
        cursor = next_cursor
        if not cursor:
            break
    log.info("webform %s submissions fetched: %d", webform_id, len(submissions))
    return submissions


def update_webform_history(db_path: Path, client: SalesmapClient, log: logging.Logger) -> None:
    if not db_path.exists():
        log.warning("DB not found for webform history update: %s", db_path)
        return
    with sqlite3.connect(db_path) as conn:
        webform_ids, allowed_people_ids = collect_webform_ids(conn, log)
        if not webform_ids:
            return
        allowed_people_set = {pid for pid in allowed_people_ids if pid}
        writer = TableWriter(conn, "webform_history")
        writer.load_existing()
        total = 0
        dropped_missing_total = 0
        dropped_not_allowed_total = 0
        for wf_id in webform_ids:
            submissions = fetch_webform_submissions(client, wf_id, log)
            filtered, dropped_missing, dropped_not_allowed = filter_submissions_by_people(
                submissions, allowed_people_set, log
            )
            if dropped_missing or dropped_not_allowed:
                log.info(
                    "webform %s submissions filtered: kept=%d dropped_missing_person=%d dropped_not_allowed=%d",
                    wf_id,
                    len(filtered),
                    dropped_missing,
                    dropped_not_allowed,
                )
            dropped_missing_total += dropped_missing
            dropped_not_allowed_total += dropped_not_allowed
            total += writer.write_batch(filtered)
        conn.commit()
    log.info(
        "webform_history updated with %d rows (db=%s, dropped_missing_person=%d, dropped_not_allowed=%d)",
        total,
        db_path,
        dropped_missing_total,
        dropped_not_allowed_total,
    )


def normalize_records(records: List[Dict[str, Any]], columns: Sequence[str]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for record in records:
        row: Dict[str, Any] = {}
        for col in columns:
            val = record.get(col)
            if isinstance(val, (dict, list)):
                row[col] = json.dumps(val, ensure_ascii=False)
            else:
                row[col] = val
        normalized.append(row)
    return normalized


def parse_webforms_field(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, (dict, list)):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except Exception:
            return []
    if isinstance(data, list):
        ids: List[str] = []
        for item in data:
            if isinstance(item, dict):
                val = item.get("id") or item.get("name")
                if val:
                    ids.append(str(val))
            elif item:
                ids.append(str(item))
        return ids
    return []


def _extract_person_id_from_submission(entry: Any) -> Optional[str]:
    if not isinstance(entry, dict):
        return None
    for key in ("peopleId", "personId", "person_id", "people_id"):
        val = entry.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    person = entry.get("person")
    if isinstance(person, dict):
        for key in ("id", "personId", "peopleId"):
            val = person.get(key)
            if val is None:
                continue
            text = str(val).strip()
            if text:
                return text
    return None


def filter_submissions_by_people(
    submissions: List[Dict[str, Any]], allowed_people_ids: Set[str], log: logging.Logger
) -> Tuple[List[Dict[str, Any]], int, int]:
    allowed = {pid for pid in allowed_people_ids if pid}
    kept: List[Dict[str, Any]] = []
    dropped_missing = 0
    dropped_not_allowed = 0
    for entry in submissions:
        person_id = _extract_person_id_from_submission(entry)
        if not person_id:
            dropped_missing += 1
            continue
        if person_id not in allowed:
            dropped_not_allowed += 1
            continue
        kept.append(entry)
    return kept, dropped_missing, dropped_not_allowed


class CheckpointManager:
    def __init__(self, directory: Path, run_tag: str, db_tmp_path: Path, initial_state: Optional[Dict[str, Any]] = None) -> None:
        self.directory = directory
        self.run_tag = run_tag
        self.path = directory / f"checkpoint_{run_tag}.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        default_state = {
            "run_tag": run_tag,
            "db_tmp_path": str(db_tmp_path),
            "tables": {},
            "created_at": now,
            "updated_at": now,
        }
        if initial_state:
            default_state.update(initial_state)
        elif self.path.exists():
            try:
                default_state = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        self.state = default_state

    def get_table(self, table: str) -> Optional[Dict[str, Any]]:
        tables = self.state.get("tables") or {}
        return tables.get(table)

    def save_table(self, table: str, payload: Dict[str, Any]) -> None:
        tables = self.state.setdefault("tables", {})
        tables[table] = payload
        self.state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                tmp_path.replace(self.path)
                return
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.2 * (attempt + 1))
        log = logging.getLogger(LOG_NAME)
        log.warning(
            "Checkpoint replace failed (tmp=%s, target=%s): %s. Trying copy fallback.",
            tmp_path,
            self.path,
            last_exc,
        )
        try:
            shutil.copyfile(tmp_path, self.path)
            tmp_path.unlink(missing_ok=True)
        except Exception as exc:
            log.error("Checkpoint copy fallback failed; leaving tmp at %s: %s", tmp_path, exc)
            raise


def load_checkpoint_file(checkpoint_dir: Path, run_tag: Optional[str]) -> Optional[Dict[str, Any]]:
    if run_tag:
        path = checkpoint_dir / f"checkpoint_{run_tag}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None
    candidates = sorted(checkpoint_dir.glob("checkpoint_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def capture_paginated(
    client: SalesmapClient,
    table_state: Dict[str, Dict[str, Any]],
    path: str,
    list_key: str,
    writer: TableWriter,
    table_name: Optional[str] = None,
    endpoint_label: Optional[str] = None,
    log: Optional[logging.Logger] = None,
    checkpoint: Optional[CheckpointManager] = None,
    checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
    resume_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    log = log or logger
    label = endpoint_label or path
    table = table_name or sanitize_table_name(label)
    entry = table_state.setdefault(table, {"endpoint": label, "errors": []})
    cursor: Optional[str] = resume_info.get("next_cursor") if resume_info else None
    page = int(resume_info.get("page", 0)) if resume_info else 0
    seen_cursors = set()
    while True:
        if cursor in seen_cursors:
            entry["errors"].append(f"page{page}:cursor_loop")
            log.error("%s cursor repeated (%s). Stopping to avoid loop.", label, cursor)
            break
        seen_cursors.add(cursor)
        params = {"cursor": cursor} if cursor else None
        payload, error = client.get_json(path, params=params)
        page += 1
        batch: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None
        if payload:
            data = payload.get("data", {})
            lst = data.get(list_key, [])
            if isinstance(lst, list):
                batch = [item for item in lst if isinstance(item, dict)]
            next_cursor = data.get("nextCursor")
        if batch:
            writer.write_batch(batch)
        log.info(
            "%s page %s -> batch=%s, total=%s, next_cursor=%s",
            label,
            page,
            len(batch),
            writer.row_count,
            "yes" if next_cursor else "no",
        )
        if error:
            entry["errors"].append(f"page{page}:{error}")
            break
        if not next_cursor:
            break
        cursor = next_cursor
        if checkpoint and (page % checkpoint_interval == 0):
            checkpoint.save_table(
                table,
                {
                    "next_cursor": cursor,
                    "page": page,
                    "rows": writer.row_count,
                    "columns": writer.columns,
                    "completed": False,
                    "errors": entry["errors"],
                },
            )
    col_count = len(writer.columns)
    completed = not error
    if checkpoint:
        checkpoint.save_table(
            table,
            {
                "next_cursor": cursor if not completed else None,
                "page": page,
                "rows": writer.row_count,
                "columns": writer.columns,
                "completed": completed,
                "errors": entry["errors"],
            },
        )
    log.info("%s -> rows=%s, cols=%s", label, writer.row_count, col_count)
    return {"table": table, "rows": writer.row_count, "columns": writer.columns, "errors": entry["errors"]}


def capture_single_list(
    client: SalesmapClient,
    table_state: Dict[str, Dict[str, Any]],
    path: str,
    list_key: str,
    writer: TableWriter,
    table_name: Optional[str] = None,
    endpoint_label: Optional[str] = None,
    log: Optional[logging.Logger] = None,
    checkpoint: Optional[CheckpointManager] = None,
    resume_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch a non-paginated list endpoint, probe columns, and write to SQLite."""
    log = log or logger
    label = endpoint_label or path
    table = table_name or sanitize_table_name(label)
    entry = table_state.setdefault(table, {"endpoint": label, "errors": []})
    payload, error = client.get_json(path)
    batch: List[Dict[str, Any]] = []
    if payload:
        data = payload.get("data", {})
        lst = data.get(list_key, [])
        if isinstance(lst, list):
            batch = [item for item in lst if isinstance(item, dict)]
    probe_columns = collect_columns(batch)
    if probe_columns and not writer.columns:
        writer.columns = probe_columns
    if writer.columns and not writer.created:
        writer._ensure_table_created()
    if batch:
        writer.write_batch(batch)
    if error:
        entry["errors"].append(f"fetch:{error}")
    col_count = len(writer.columns)
    completed = not error
    if checkpoint:
        checkpoint.save_table(
            table,
            {
                "next_cursor": None,
                "page": 1,
                "rows": writer.row_count,
                "columns": writer.columns,
                "completed": completed,
                "errors": entry["errors"],
            },
        )
    log.info("%s -> rows=%s, cols=%s", label, writer.row_count, col_count)
    return {"table": table, "rows": writer.row_count, "columns": writer.columns, "errors": entry["errors"]}


def write_outputs(
    tables: Dict[str, Dict[str, Any]],
    manifest: List[Dict[str, Any]],
    db_path: str,
    run_info: Dict[str, Any],
) -> None:
    with sqlite3.connect(db_path) as conn:
        for table_name, payload in tables.items():
            df = pd.DataFrame(payload["records"], columns=payload["columns"])
            df.to_sql(table_name, conn, if_exists="replace", index=False)
        pd.DataFrame(manifest).to_sql("manifest", conn, if_exists="replace", index=False)
        pd.DataFrame([run_info]).to_sql("run_info", conn, if_exists="replace", index=False)


def _list_tables(con: sqlite3.Connection) -> List[str]:
    cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cur.fetchall() if not row[0].startswith("sqlite_")]


def _dump_table_jsonl(con: sqlite3.Connection, table: str, zf: zipfile.ZipFile) -> None:
    cursor = con.execute(f'SELECT * FROM "{table}"')
    cols = [desc[0] for desc in cursor.description] if cursor.description else []
    zf.writestr(f"schemas/{table}_columns.json", json.dumps(cols, ensure_ascii=False, indent=2))
    with zf.open(f"{table}.jsonl", "w") as raw:
        wrapper = io.TextIOWrapper(raw, encoding="utf-8")
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                obj = {col: _serialize_value(val) for col, val in zip(cols, row)}
                wrapper.write(json.dumps(obj, ensure_ascii=False))
                wrapper.write("\n")
        wrapper.flush()


def maybe_backup_existing_db(
    db_path: Path,
    backup_dir: Path,
    keep_backups: int,
    enabled: bool = True,
) -> Optional[Path]:
    if not enabled or not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        run_tag: Optional[str] = None
        run_info_row: Dict[str, Any] = {}
        try:
            df = pd.read_sql_query("SELECT * FROM run_info LIMIT 1", con)
            if not df.empty:
                run_info_row = {k: _serialize_value(v) for k, v in df.iloc[0].to_dict().items()}
                run_tag = str(run_info_row.get("run_tag") or "").strip() or None
        except Exception:
            pass
        if not run_tag:
            ts = datetime.datetime.fromtimestamp(db_path.stat().st_mtime, tz=datetime.timezone.utc)
            run_tag = ts.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"salesmap_backup_{run_tag}.zip"
        tables = _list_tables(con)
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if run_info_row:
                zf.writestr("run_info.json", json.dumps(run_info_row, ensure_ascii=False, indent=2))
            for table in tables:
                _dump_table_jsonl(con, table, zf)
        existing = sorted(backup_dir.glob("salesmap_backup_*.zip"))
        if keep_backups is not None and keep_backups >= 0 and len(existing) > keep_backups:
            to_delete = existing[: len(existing) - keep_backups]
            for old in to_delete:
                try:
                    old.unlink()
                except Exception:
                    continue
        return backup_path


def finalize_sqlite_connection(
    conn: sqlite3.Connection,
    log: Optional[logging.Logger] = None,
    sleep_after: float = 0.5,
) -> None:
    """Flush, checkpoint, and close a SQLite connection before file moves."""
    log = log or logger
    try:
        conn.commit()
    except Exception as exc:
        log.warning("SQLite commit during finalize failed: %s", exc)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as exc:
        log.info("wal_checkpoint skipped: %s", exc)
    try:
        conn.execute("PRAGMA optimize")
    except Exception as exc:
        log.info("PRAGMA optimize skipped: %s", exc)
    try:
        conn.close()
    except Exception as exc:
        log.warning("SQLite close during finalize failed: %s", exc)
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    if sleep_after > 0:
        try:
            time.sleep(sleep_after)
        except Exception:
            pass


def _describe_blocking_processes(path: Path, log: logging.Logger) -> None:
    """Log processes that currently hold a handle to path (best effort)."""
    try:
        import psutil  # type: ignore
    except Exception:
        return

    target = os.path.abspath(path)
    blockers = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            for opened in proc.open_files():
                opened_path = os.path.abspath(opened.path)
                if opened_path.lower() == target.lower():
                    blockers.append(f"{proc.info.get('name') or 'pid'} (pid {proc.info.get('pid')})")
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    if blockers:
        log.warning("File lock detected on %s by: %s", path, "; ".join(blockers))


def replace_file_with_retry(
    src: Path,
    dest: Path,
    attempts: int = 5,
    delay: float = 0.5,
    log: Optional[logging.Logger] = None,
    run_tag: Optional[str] = None,
) -> Path:
    log = log or logger
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            os.replace(src, dest)
            return dest
        except PermissionError as exc:
            last_exc = exc
            log.warning("Replace attempt %s/%s failed due to lock: %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(delay)
        except OSError as exc:
            last_exc = exc
            log.error("Replace attempt %s/%s failed: %s", attempt, attempts, exc)
            break
    if last_exc:
        _describe_blocking_processes(dest, log)
        fallback_tag = run_tag or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        fallback_path = dest.parent / f"{dest.stem}_{fallback_tag}{dest.suffix}"
        try:
            os.replace(src, fallback_path)
            log.error(
                "Failed to replace locked DB %s after %s attempts. New DB kept at %s. Last error: %s",
                dest,
                attempts,
                fallback_path,
                last_exc,
            )
            return fallback_path
        except PermissionError as exc:
            log.warning("Fallback replace failed, attempting copy: %s", exc)
            try:
                shutil.copyfile(src, fallback_path)
                log.error(
                    "Failed to replace locked DB %s after %s attempts. Copied tmp to %s. Last replace error: %s",
                    dest,
                    attempts,
                    fallback_path,
                    last_exc,
                )
                return fallback_path
            except Exception as exc2:  # pragma: no cover - double failure is unexpected
                log.error("Failed to copy tmp DB to fallback path %s: %s", fallback_path, exc2)
        except Exception as exc:  # pragma: no cover - unexpected
            log.error("Failed to move tmp DB to fallback path %s: %s", fallback_path, exc)
        raise last_exc


def setup_logging(log_dir: Path, run_tag: str) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"salesmap_snapshot_{run_tag}.log"
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return log_path


def record_run_history(
    log_dir: Path,
    run_info: Dict[str, Any],
    manifest: List[Dict[str, Any]],
    log_path: Path,
    backup_path: Optional[Path],
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    history_path = log_dir / "run_history.jsonl"
    errors = [m for m in manifest if m.get("errors")]
    summary = {
        "run_tag": run_info.get("run_tag"),
        "captured_at_utc": run_info.get("captured_at_utc"),
        "final_db_path": run_info.get("final_db_path"),
        "log_path": str(log_path),
        "backup_path": str(backup_path) if backup_path else None,
        "tables": {m["table"]: {"rows": m["row_count"], "cols": m["column_count"]} for m in manifest},
        "errors": {"count": len(errors), "details": [m for m in errors]},
    }
    with history_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(summary, ensure_ascii=False))
        fp.write("\n")
    return history_path


def finalize_tables(registry: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    tables: Dict[str, Dict[str, Any]] = {}
    manifest: List[Dict[str, Any]] = []
    for table_name, entry in registry.items():
        columns = collect_columns(entry["records"])
        normalized = normalize_records(entry["records"], columns) if columns else []
        columns_for_df = columns if columns else ["__no_data"]
        tables[table_name] = {"records": normalized, "columns": columns_for_df}
        manifest.append(
            {
                "table": table_name,
                "endpoint": entry["endpoint"],
                "row_count": len(normalized),
                "column_count": len(columns),
                "errors": ";".join(entry["errors"]),
            }
        )
    return tables, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Salesmap API full snapshot (cursor to end) to SQLite.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Output SQLite path.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Salesmap API base URL.")
    parser.add_argument("--token", default=None, help="Salesmap API token (overrides env/secrets).")
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR, help="Directory to store compressed backups.")
    parser.add_argument("--keep-backups", type=int, default=DEFAULT_KEEP_BACKUPS, help="Number of backups to retain.")
    parser.add_argument("--no-backup", action="store_true", help="Disable backup creation before overwrite.")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help="Directory to store run logs and history.")
    parser.add_argument(
        "--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR, help="Directory to store resume checkpoints."
    )
    parser.add_argument(
        "--checkpoint-interval", type=int, default=DEFAULT_CHECKPOINT_INTERVAL, help="Pages per checkpoint save."
    )
    parser.add_argument("--resume", action="store_true", help="Resume from the latest checkpoint if present.")
    parser.add_argument("--resume-run-tag", default=None, help="Resume from a specific checkpoint run_tag.")
    parser.add_argument(
        "--webform-only",
        action="store_true",
        help="Skip snapshot crawl and only update webform_history on the existing DB.",
    )
    args = parser.parse_args()

    token = _load_token(args.token)
    if not token:
        raise SystemExit("SALESMAP_TOKEN is required (env or streamlit secrets).")

    db_path = Path(args.db_path)
    client = SalesmapClient(base_url=args.base_url, token=token)

    if args.webform_only:
        run_ts = datetime.datetime.now(datetime.timezone.utc)
        log_dir = Path(args.log_dir)
        setup_logging(log_dir, run_ts.strftime("%Y%m%d_%H%M%S"))
        logger.info("Starting webform-only update on %s", db_path)
        update_webform_history(db_path, client, logger)
        logger.info("Done webform-only update.")
        return

    run_ts = datetime.datetime.now(datetime.timezone.utc)
    checkpoint_dir = Path(args.checkpoint_dir)
    resume_state = load_checkpoint_file(checkpoint_dir, args.resume_run_tag if args.resume else None) if args.resume else None
    run_tag = (resume_state.get("run_tag") if resume_state else None) or run_ts.strftime("%Y%m%d_%H%M%S")
    log_dir = Path(args.log_dir)
    log_path = setup_logging(log_dir, run_tag)
    logger.info("Starting Salesmap snapshot run %s (resume=%s)", run_tag, bool(resume_state))
    if args.resume and not resume_state:
        logger.info("Resume requested but no checkpoint found. Starting fresh.")

    backup_dir = Path(args.backup_dir)
    backup_created = maybe_backup_existing_db(db_path, backup_dir, args.keep_backups, enabled=not args.no_backup)
    if backup_created:
        logger.info("Backup created: %s", backup_created)
    elif db_path.exists():
        logger.info("Existing DB found at %s (backup skipped or disabled)", db_path)

    tmp_path = Path(resume_state["db_tmp_path"]) if resume_state and resume_state.get("db_tmp_path") else db_path.with_suffix(db_path.suffix + ".tmp")
    if not resume_state and tmp_path.exists():
        try:
            tmp_path.unlink()
            logger.info("Removed existing temp DB at %s", tmp_path)
        except Exception as exc:
            logger.warning("Failed to remove existing temp DB %s: %s. Using alternate temp path.", tmp_path, exc)
            tmp_path = db_path.with_name(f"{db_path.stem}_{run_tag}{db_path.suffix}.tmp")
    checkpoint_mgr = CheckpointManager(checkpoint_dir, run_tag, tmp_path, initial_state=resume_state)

    client = SalesmapClient(base_url=args.base_url, token=token)
    table_state: Dict[str, Dict[str, Any]] = {}
    writers: Dict[str, TableWriter] = {}
    paginated_endpoints = [
        ("/organization", "organizationList", "organization"),
        ("/people", "peopleList", "people"),
        ("/deal", "dealList", "deal"),
        ("/lead", "leadList", "lead"),
        ("/memo", "memoList", "memo"),
    ]
    single_endpoints = [
        ("/user", "userList", "user"),
        ("/team", "teamList", "team"),
    ]
    all_endpoints = [p for p, _, _ in paginated_endpoints + single_endpoints]

    run_info: Dict[str, Any] = {
        "run_tag": run_tag,
        "captured_at_utc": run_ts.isoformat().replace("+00:00", "Z"),
        "base_url": client.base_url,
        "endpoints": json.dumps(all_endpoints, ensure_ascii=False),
        "note": "",
        "checkpoint_path": str(checkpoint_mgr.path),
    }

    manifest: List[Dict[str, Any]] = []
    conn = sqlite3.connect(tmp_path)
    try:
        for path, list_key, table in paginated_endpoints:
            writer = TableWriter(conn, table)
            writer.load_existing()
            if resume_state:
                cp_entry = resume_state.get("tables", {}).get(table)
                if cp_entry and not writer.columns and cp_entry.get("columns"):
                    writer.columns = cp_entry.get("columns", [])
                    writer._ensure_table_created()
                    writer.row_count = int(cp_entry.get("rows", 0) or 0)
                    writer.created = bool(writer.columns)
                elif cp_entry and writer.row_count != int(cp_entry.get("rows", 0) or 0):
                    logger.warning(
                        "Checkpoint row count (%s) for %s differs from existing table rows (%s)",
                        cp_entry.get("rows"),
                        table,
                        writer.row_count,
                    )
            writers[table] = writer
            resume_info = checkpoint_mgr.get_table(table) if resume_state else None
            capture_paginated(
                client,
                table_state,
                path,
                list_key=list_key,
                writer=writer,
                table_name=table,
                log=logger,
                checkpoint=checkpoint_mgr,
                checkpoint_interval=max(1, args.checkpoint_interval),
                resume_info=resume_info,
            )

        for path, list_key, table in single_endpoints:
            writer = TableWriter(conn, table)
            writer.load_existing()
            if resume_state:
                cp_entry = resume_state.get("tables", {}).get(table)
                if cp_entry and not writer.columns and cp_entry.get("columns"):
                    writer.columns = cp_entry.get("columns", [])
                    writer._ensure_table_created()
                    writer.row_count = int(cp_entry.get("rows", 0) or 0)
                    writer.created = bool(writer.columns)
                elif cp_entry and writer.row_count != int(cp_entry.get("rows", 0) or 0):
                    logger.warning(
                        "Checkpoint row count (%s) for %s differs from existing table rows (%s)",
                        cp_entry.get("rows"),
                        table,
                        writer.row_count,
                    )
            writers[table] = writer
            resume_info = checkpoint_mgr.get_table(table) if resume_state else None
            capture_single_list(
                client,
                table_state,
                path,
                list_key=list_key,
                writer=writer,
                table_name=table,
                log=logger,
                checkpoint=checkpoint_mgr,
                resume_info=resume_info,
            )

        for table, entry in table_state.items():
            writer = writers.get(table)
            columns_len = len(writer.columns) if writer else 0
            manifest.append(
                {
                    "table": table,
                    "endpoint": entry["endpoint"],
                    "row_count": writer.row_count if writer else 0,
                    "column_count": columns_len,
                    "errors": ";".join(entry["errors"]),
                }
            )
        manifest_df = pd.DataFrame(manifest)
        manifest_df.to_sql("manifest", conn, if_exists="replace", index=False)

        pd.DataFrame([run_info]).to_sql("run_info", conn, if_exists="replace", index=False)
    finally:
        finalize_sqlite_connection(conn, log=logger)

    final_db_path = replace_file_with_retry(tmp_path, db_path, log=logger, run_tag=run_tag)
    if final_db_path != db_path:
        logger.warning("Target DB locked; new snapshot stored at %s (original left untouched)", final_db_path)
    run_info["final_db_path"] = str(final_db_path)
    with sqlite3.connect(final_db_path) as conn:
        pd.DataFrame([run_info]).to_sql("run_info", conn, if_exists="replace", index=False)
    try:
        update_webform_history(Path(final_db_path), client, logger)
    except Exception as exc:  # pragma: no cover - best-effort post step
        logger.warning("webform history update failed: %s", exc)

    history_path = record_run_history(log_dir, run_info, manifest, log_path, backup_created)
    logger.info("Run history appended to %s", history_path)
    logger.info("Done. SQLite -> %s", final_db_path)


if __name__ == "__main__":
    main()

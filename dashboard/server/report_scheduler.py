from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .deal_normalizer import build_counterparty_risk_report, DB_PATH, _connect
from .agents.core.artifacts import ArtifactStore
from .agents.core.orchestrator import Orchestrator
from .agents.core.types import AgentContext, LLMConfig
from .agents.registry import (
    REPORT_ID_COUNTERPARTY_PROGRESS_DAILY,
    get_agent_chain,
)
from .report.progress_universe import build_progress_universe, build_l1_payload

TZ = os.getenv("TZ", "Asia/Seoul")
REPORT_CRON = os.getenv("REPORT_CRON", "0 8 * * *")
CACHE_DIR = Path(os.getenv("CACHE_DIR", "report_cache"))
WORK_DIR = Path(os.getenv("WORK_DIR", "report_work"))
DB_STABLE_WINDOW_SEC = int(os.getenv("DB_STABLE_WINDOW_SEC", "180"))
DB_RETRY = int(os.getenv("DB_RETRY", "10"))
DB_RETRY_INTERVAL_SEC = int(os.getenv("DB_RETRY_INTERVAL_SEC", "30"))
CACHE_RETENTION_DAYS = int(os.getenv("CACHE_RETENTION_DAYS", "14"))
LOCK_PATH = CACHE_DIR / ".counterparty_risk.lock"
GENERATOR_VERSION = "d7-v1"
_SCHEDULER_INSTANCE: Optional[BackgroundScheduler] = None
ALLOWED_MODES = {"offline", "online"}
PROGRESS_CRON = os.getenv("PROGRESS_CRON", "0 6 * * *")
ENABLE_PROGRESS_SCHEDULER = os.getenv("ENABLE_PROGRESS_SCHEDULER", "0") == "1"


def _db_signature(db_path: Path) -> str:
    stat = db_path.stat()
    return f"{int(stat.st_mtime)}-{stat.st_size}"


def _normalize_mode(mode: Optional[str]) -> str:
    m = (mode or "offline").lower()
    if m not in ALLOWED_MODES:
        raise ValueError(f"Invalid mode: {mode}")
    return m


@contextlib.contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR)
    acquired = False
    try:
        if os.name == "posix":
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        else:
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError as exc:
                raise BlockingIOError("Failed to acquire lock") from exc
        yield
    finally:
        if acquired:
            if os.name == "posix":
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        os.close(fd)


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _cleanup_old(retention_days: int = CACHE_RETENTION_DAYS):
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    status_files = {"status.json", "status_online.json"}
    for p in CACHE_DIR.rglob("*.json"):
        if p.name in status_files:
            continue
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < cutoff:
                p.unlink()
        except Exception:
            continue
    run_logs = CACHE_DIR / "run_logs"
    for p in run_logs.glob("*.jsonl"):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < cutoff:
                p.unlink()
        except Exception:
            continue
    snapshots = WORK_DIR.glob("salesmap_snapshot_*.db")
    for p in snapshots:
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < cutoff:
                p.unlink()
        except Exception:
            continue


def _db_stable(db_path: Path) -> bool:
    stat = db_path.stat()
    age = time.time() - stat.st_mtime
    return age >= DB_STABLE_WINDOW_SEC


def _make_snapshot(db_path: Path, as_of: str) -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    snap = WORK_DIR / f"salesmap_snapshot_{as_of}_{ts}.db"
    shutil.copy2(db_path, snap)
    return snap


def _status_path(mode: str = "offline") -> Path:
    return CACHE_DIR / ("status.json" if mode == "offline" else "status_online.json")


def _load_status(mode: str = "offline") -> Dict[str, Any]:
    p = _status_path(mode)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_status(data: Dict[str, Any], mode: str = "offline") -> None:
    _atomic_write(_status_path(mode), data)


def _progress_status_path() -> Path:
    return CACHE_DIR / "status_progress.json"


def _load_progress_status() -> Dict[str, Any]:
    p = _progress_status_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_progress_status(data: Dict[str, Any]) -> None:
    _atomic_write(_progress_status_path(), data)


def _report_cache_path(as_of: date | str, mode: str) -> Path:
    as_of_str = as_of if isinstance(as_of, str) else as_of.isoformat()
    if mode == "offline":
        return CACHE_DIR / f"{as_of_str}.json"
    return CACHE_DIR / "counterparty-risk" / mode / f"{as_of_str}.json"


def _progress_cache_dir(as_of: date | str, mode: str) -> Path:
    as_of_str = as_of if isinstance(as_of, str) else as_of.isoformat()
    return CACHE_DIR / "llm_progress" / as_of_str / _db_signature(DB_PATH)


REPORT_MODES = [m.strip() for m in os.getenv("REPORT_MODES", "offline,online").split(",") if m.strip()]


def run_daily_counterparty_risk_job(as_of_date: Optional[str] = None, force: bool = False, mode: str = "offline", acquire_lock: bool = True) -> Dict[str, Any]:
    mode_norm = _normalize_mode(mode)
    as_of = as_of_date or date.today().isoformat()
    cache_path = _report_cache_path(as_of, mode_norm)
    status = _load_status(mode_norm)
    job_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def _run() -> Dict[str, Any]:
        if not force and cache_path.exists():
            try:
                cached_meta = json.loads(cache_path.read_text(encoding="utf-8")).get("meta", {})
                if cached_meta.get("as_of") == as_of:
                    status["last_run"] = {
                        "generated_at": datetime.now().isoformat(),
                        "result": "SKIPPED_CACHE",
                        "as_of": as_of,
                        "mode": mode_norm,
                    }
                    _save_status(status, mode_norm)
                    return {"result": "SKIPPED_CACHE", "cache": str(cache_path)}
            except Exception:
                pass

        # DB stability check with retries
        db_ready = False
        db_signature = None
        for attempt in range(DB_RETRY):
            if DB_PATH.exists() and _db_stable(DB_PATH):
                db_ready = True
                db_signature = _db_signature(DB_PATH)
                break
            time.sleep(DB_RETRY_INTERVAL_SEC)

        if not db_ready:
            status["last_run"] = {
                "generated_at": datetime.now().isoformat(),
                "result": "FAILED",
                "error_code": "DB_UNSTABLE_OR_UPDATING",
                "as_of": as_of,
                "mode": mode_norm,
            }
            _save_status(status, mode_norm)
            raise FileNotFoundError("DB unstable or not found")

        snapshot_path = _make_snapshot(DB_PATH, as_of)

        try:
            report = build_counterparty_risk_report(as_of_date=as_of, db_path=snapshot_path, mode_key=mode_norm)
            report["meta"]["db_signature"] = db_signature
            report["meta"]["generator_version"] = GENERATOR_VERSION
            report["meta"]["job_run_id"] = job_run_id
            _atomic_write(cache_path, report)
            status["last_run"] = {
                "generated_at": datetime.now().isoformat(),
                "result": "SUCCESS",
                "as_of": as_of,
                "mode": mode_norm,
                "db_signature": db_signature,
            }
            status["last_success"] = {
                "generated_at": datetime.now().isoformat(),
                "as_of": as_of,
                "mode": mode_norm,
                "db_signature": db_signature,
            }
            _save_status(status, mode_norm)
            _cleanup_old()
            return {"result": "SUCCESS", "cache": str(cache_path)}
        except Exception as exc:
            status["last_run"] = {
                "generated_at": datetime.now().isoformat(),
                "result": "FAILED",
                "error_code": "PIPELINE_FAILED",
                "error_message": str(exc),
                "as_of": as_of,
                "mode": mode_norm,
            }
            _save_status(status, mode_norm)
            raise

    try:
        if acquire_lock:
            with file_lock(LOCK_PATH):
                return _run()
        return _run()
    except BlockingIOError:
        status["last_run"] = {
            "generated_at": datetime.now().isoformat(),
            "result": "SKIPPED_LOCKED",
            "as_of": as_of,
            "mode": mode_norm,
        }
        _save_status(status, mode_norm)
        return {"result": "SKIPPED_LOCKED", "as_of": as_of}


def run_daily_counterparty_risk_job_all_modes(as_of_date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    as_of = as_of_date or date.today().isoformat()
    try:
        with file_lock(LOCK_PATH):
            for mode in REPORT_MODES or ["offline"]:
                mode_norm = _normalize_mode(mode)
                results[mode_norm] = run_daily_counterparty_risk_job(as_of_date=as_of, force=force, mode=mode_norm, acquire_lock=False)
    except BlockingIOError:
        for mode in REPORT_MODES or ["offline"]:
            mode_norm = _normalize_mode(mode)
            results[mode_norm] = {"result": "SKIPPED_LOCKED", "as_of": as_of, "mode": mode_norm}
    return results


def run_daily_counterparty_progress_job_all_modes(force: bool = False) -> Dict[str, Any]:
    """
    Progress L1 precompute. Reuses lock; builds universe, payloads, and populates LLM caches.
    """
    results: Dict[str, Any] = {}
    as_of = date.today().isoformat()
    status = _load_progress_status()
    job_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def _run_one(mode: str) -> Dict[str, Any]:
        db_ready = False
        db_signature = None
        for attempt in range(DB_RETRY):
            if DB_PATH.exists() and _db_stable(DB_PATH):
                db_ready = True
                db_signature = _db_signature(DB_PATH)
                break
            time.sleep(DB_RETRY_INTERVAL_SEC)
        if not db_ready:
            return {
                "result": "FAILED",
                "error_code": "DB_UNSTABLE_OR_UPDATING",
                "as_of": as_of,
                "mode": mode,
            }
        db_mtime_iso = datetime.fromtimestamp(Path(DB_PATH).stat().st_mtime, timezone.utc).isoformat()
        db_hash = hashlib.sha256(db_mtime_iso.encode("utf-8")).hexdigest()[:16]
        snap_path = _make_snapshot(DB_PATH, as_of)
        try:
            # build universe + payloads
            universe = build_progress_universe(as_of=as_of, mode=mode, snapshot_db_path=snap_path)
            payloads = [build_l1_payload(k, as_of=as_of, mode=mode, snapshot_db_path=snap_path).model_dump() for k in universe]

            # Agent execution (fan-out)
            artifacts = ArtifactStore()
            artifacts.set("base.counterparty_rows", payloads)
            ctx = AgentContext(
                report_id=REPORT_ID_COUNTERPARTY_PROGRESS_DAILY,
                mode_key=mode,
                as_of_date=date.fromisoformat(as_of),
                db_hash=db_hash,
                snapshot_db_path=snap_path,
                cache_root=CACHE_DIR,
                llm=LLMConfig.from_env(),
            )
            agents = get_agent_chain(REPORT_ID_COUNTERPARTY_PROGRESS_DAILY, mode)
            orchestrator = Orchestrator()
            with _connect(snap_path) as conn:
                orchestrator.run(REPORT_ID_COUNTERPARTY_PROGRESS_DAILY, mode, ctx, artifacts, agents, conn=conn)

            return {
                "result": "SUCCESS",
                "as_of": as_of,
                "mode": mode,
                "snapshot": str(snap_path),
                "db_signature": db_signature,
                "db_hash": db_hash,
                "job_run_id": job_run_id,
                "payload_count": len(payloads),
            }
        except Exception as exc:
            return {
                "result": "FAILED",
                "error_code": "PIPELINE_FAILED",
                "error_message": str(exc),
                "as_of": as_of,
                "mode": mode,
            }

    try:
        with file_lock(LOCK_PATH):
            for mode in ["offline", "online"]:
                results[mode] = _run_one(mode)
            status["last_run"] = {
                "generated_at": datetime.now().isoformat(),
                "result": "SUCCESS",
                "as_of": as_of,
                "modes": list(results.keys()),
                "job_run_id": job_run_id,
            }
            status["last_success"] = status.get("last_run", {})
            _save_progress_status(status)
            _cleanup_old()
    except BlockingIOError:
        status["last_run"] = {
            "generated_at": datetime.now().isoformat(),
            "result": "SKIPPED_LOCKED",
            "as_of": as_of,
        }
        _save_progress_status(status)
        results["all"] = {"result": "SKIPPED_LOCKED", "as_of": as_of}
    return results


def get_cached_report(as_of: Optional[str] = None, mode: str = "offline") -> Dict[str, Any]:
    mode_norm = _normalize_mode(mode)
    as_of = as_of or date.today().isoformat()
    cache_path = _report_cache_path(as_of, mode_norm)
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    status = _load_status(mode_norm)
    last_success = status.get("last_success")
    if last_success:
        fallback_path = _report_cache_path(last_success.get("as_of"), mode_norm)
        if fallback_path.exists():
            data = json.loads(fallback_path.read_text(encoding="utf-8"))
            data.setdefault("meta", {})["is_stale"] = True
            data["meta"]["stale_reason"] = "latest_success_fallback"
            return data
    raise FileNotFoundError("No report cache available")


def start_scheduler():
    """
    Start APScheduler once per process (guarded for reload/multi-start).
    Set ENABLE_SCHEDULER=0 to skip in tests.
    """
    global _SCHEDULER_INSTANCE
    if os.getenv("ENABLE_SCHEDULER", "1") == "0":
        return None
    if _SCHEDULER_INSTANCE:
        return _SCHEDULER_INSTANCE

    scheduler = BackgroundScheduler(timezone=TZ)
    cron = CronTrigger.from_crontab(REPORT_CRON, timezone=TZ)
    scheduler.add_job(run_daily_counterparty_risk_job_all_modes, cron, max_instances=1, coalesce=True)
    if ENABLE_PROGRESS_SCHEDULER:
        progress_cron = CronTrigger.from_crontab(PROGRESS_CRON, timezone=TZ)
        scheduler.add_job(run_daily_counterparty_progress_job_all_modes, progress_cron, max_instances=1, coalesce=True)
    scheduler.start()
    _SCHEDULER_INSTANCE = scheduler
    return scheduler

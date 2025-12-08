import json
import logging
import sys
import tempfile
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

try:
    import pandas  # type: ignore
except ModuleNotFoundError:
    pd_stub = types.ModuleType("pandas")

    class _DummyFrame:
        def __init__(self, data=None, columns=None, **kwargs):
            self._data = data if data is not None else []
            self._columns = columns if columns is not None else []

        @property
        def empty(self):
            return not bool(self._data)

        @property
        def columns(self):
            return self._columns

        def to_sql(self, *args, **kwargs):
            return None

        def to_dict(self):
            return {}

        @property
        def iloc(self):
            class _Loc:
                def __getitem__(self, idx):
                    return self

                def to_dict(self):
                    return {}

            return _Loc()

    pd_stub.DataFrame = _DummyFrame
    pd_stub.read_sql_query = lambda *args, **kwargs: _DummyFrame()
    sys.modules["pandas"] = pd_stub

import salesmap_first_page_snapshot as snap


def quiet_logger(name: str = "salesmap_test") -> logging.Logger:
    log = logging.getLogger(name)
    log.handlers.clear()
    log.addHandler(logging.NullHandler())
    return log


class ReplaceFileRetryTest(TestCase):
    def test_replace_file_with_retry_recovers_from_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "tmp.db"
            dest = Path(tmpdir) / "final.db"
            src.write_text("new")
            dest.write_text("old")

            call_count = {"n": 0}

            def fake_replace(src_path: Path, dest_path: Path) -> None:
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise PermissionError("locked")
                dest_path.write_text(Path(src_path).read_text())
                Path(src_path).unlink(missing_ok=True)

            with patch("salesmap_first_page_snapshot.os.replace", side_effect=fake_replace):
                with patch("salesmap_first_page_snapshot.time.sleep") as sleep_mock:
                    snap.replace_file_with_retry(src, dest, attempts=2, delay=0, log=quiet_logger())
                    sleep_mock.assert_called_once()

            self.assertEqual(dest.read_text(), "new")
            self.assertFalse(src.exists())
            self.assertEqual(call_count["n"], 2)

    def test_replace_file_with_retry_keeps_fallback_when_lock_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "tmp.db"
            dest = Path(tmpdir) / "final.db"
            src.write_text("new")
            dest.write_text("old")

            def fake_replace(src_path: Path, dest_path: Path) -> None:
                if dest_path == dest:
                    raise PermissionError("locked")
                dest_path.write_text(Path(src_path).read_text())
                Path(src_path).unlink(missing_ok=True)

            with patch("salesmap_first_page_snapshot.os.replace", side_effect=fake_replace):
                fallback = snap.replace_file_with_retry(
                    src, dest, attempts=2, delay=0, log=quiet_logger(), run_tag="tag123"
                )

            self.assertFalse(src.exists())
            self.assertEqual(fallback, dest.parent / "final_tag123.db")
            self.assertEqual(fallback.read_text(), "new")
            self.assertEqual(dest.read_text(), "old")

    def test_replace_file_with_retry_copies_when_fallback_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "tmp.db"
            dest = Path(tmpdir) / "final.db"
            src.write_text("new")
            dest.write_text("old")

            with patch("salesmap_first_page_snapshot.os.replace", side_effect=PermissionError("locked")):
                fallback = snap.replace_file_with_retry(
                    src, dest, attempts=1, delay=0, log=quiet_logger(), run_tag="tag999"
                )

            self.assertEqual(fallback.read_text(), "new")
            self.assertEqual(dest.read_text(), "old")


class FinalizeConnectionTest(TestCase):
    def test_finalize_sqlite_connection_runs_checkpoint_and_close(self) -> None:
        calls = []

        class FakeConn:
            def commit(self):
                calls.append("commit")

            def execute(self, sql):
                calls.append(sql)

            def close(self):
                calls.append("close")

        with patch("gc.collect") as gc_mock:
            snap.finalize_sqlite_connection(FakeConn(), log=quiet_logger(), sleep_after=0)
            gc_mock.assert_called_once()

        self.assertEqual(
            calls,
            ["commit", "PRAGMA wal_checkpoint(TRUNCATE)", "PRAGMA optimize", "close"],
        )


class RunHistoryTest(TestCase):
    def test_record_run_history_appends_json_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            run_info = {"run_tag": "testtag", "captured_at_utc": "2024-01-01T00:00:00Z"}
            manifest = [
                {"table": "people", "row_count": 3, "column_count": 2, "errors": ""},
                {"table": "deal", "row_count": 0, "column_count": 0, "errors": "page1:http_500"},
            ]
            history_path = snap.record_run_history(log_dir, run_info, manifest, Path(tmpdir) / "run.log", None)
            history_lines = history_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(history_lines), 1)
            recorded = json.loads(history_lines[0])
            self.assertEqual(recorded["run_tag"], "testtag")
            self.assertEqual(recorded["errors"]["count"], 1)
            self.assertIn("deal", recorded["tables"])


class CapturePaginatedTest(TestCase):
    def test_capture_paginated_collects_pages_and_stops_on_end(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.base_url = "http://example.test"
                self.calls = 0

            def get_json(self, path: str, params=None):
                self.calls += 1
                if self.calls == 1:
                    return {"data": {"items": [{"id": 1}, {"id": 2}], "nextCursor": "abc"}}, None
                if self.calls == 2:
                    return {"data": {"items": [{"id": 3}]}}, None
                return None, "should_not_happen"

        table_state: dict = {}
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            with snap.sqlite3.connect(Path(tmpdir) / "test.db") as conn:
                writer = snap.TableWriter(conn, "items")
                snap.capture_paginated(
                    client,
                    table_state,
                    "/items",
                    list_key="items",
                    writer=writer,
                    table_name="items",
                    endpoint_label="items",
                    log=quiet_logger(),
                )

        self.assertIn("items", table_state)
        entry = table_state["items"]
        self.assertEqual(writer.row_count, 3)
        self.assertEqual(entry["errors"], [])


class FinalizeTablesTest(TestCase):
    def test_finalize_tables_adds_placeholder_column_when_empty(self) -> None:
        registry = {"empty": {"endpoint": "empty", "records": [], "errors": []}}
        tables, manifest = snap.finalize_tables(registry)
        self.assertEqual(tables["empty"]["columns"], ["__no_data"])
        self.assertEqual(manifest[0]["row_count"], 0)


class TableWriterTest(TestCase):
    def test_table_writer_adds_new_columns_and_counts_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with snap.sqlite3.connect(Path(tmpdir) / "w.db") as conn:
                writer = snap.TableWriter(conn, "sample")
                writer.write_batch([{"a": 1, "b": 2}])
                writer.write_batch([{"a": 3, "c": 4}])
                self.assertEqual(writer.row_count, 2)
                self.assertIn("c", writer.columns)


class CheckpointManagerTest(TestCase):
    def test_checkpoint_manager_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cp_dir = Path(tmpdir) / "cp"
            mgr = snap.CheckpointManager(cp_dir, "tag1", Path(tmpdir) / "tmp.db")
            mgr.save_table("memo", {"next_cursor": "abc", "page": 5, "rows": 100, "columns": ["id"], "completed": False})
            loaded = snap.load_checkpoint_file(cp_dir, "tag1")
            self.assertIsNotNone(loaded)
            self.assertIn("memo", loaded["tables"])

import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
import types

# Stub openpyxl to avoid heavy dependency during import.
if "openpyxl" not in sys.modules:
    sys.modules["openpyxl"] = types.SimpleNamespace(load_workbook=lambda *args, **kwargs: None, Workbook=None)

from dashboard.server import database as db


def _build_base_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE deal (
          id TEXT,
          organizationId TEXT,
          peopleId TEXT,
          "이름" TEXT,
          "담당자" TEXT,
          "상태" TEXT,
          "성사 가능성" TEXT,
          "금액" TEXT,
          "예상 체결액" TEXT,
          "수주 예정일" TEXT,
          "계약 체결일" TEXT,
          "수강시작일" TEXT,
          "수강종료일" TEXT,
          "과정포맷" TEXT,
          "카테고리" TEXT,
          "코스 ID" TEXT,
          "(온라인)입과 주기" TEXT,
          "(온라인)입과 첫 회차" TEXT,
          "강사 이름1" TEXT,
          "강사비1" TEXT,
          "제안서 작성 여부" TEXT,
          "업로드 제안서명" TEXT,
          "생성 날짜" TEXT
        );
        CREATE TABLE people (
          id TEXT,
          "이름" TEXT,
          "소속 상위 조직" TEXT,
          "팀(명함/메일서명)" TEXT,
          "직급(명함/메일서명)" TEXT,
          "담당 교육 영역" TEXT,
          organizationId TEXT
        );
        CREATE TABLE organization (
          id TEXT,
          "이름" TEXT,
          "기업 규모" TEXT
        );
        """
    )
    conn.execute('INSERT INTO organization (id, "이름", "기업 규모") VALUES ("org1", "테스트기업", "대기업")')
    # p1: 메타 결측 상태로 설정 (R13/R17 트리거 목적)
    conn.execute(
        'INSERT INTO people (id, "이름", "소속 상위 조직", "팀(명함/메일서명)", "직급(명함/메일서명)", "담당 교육 영역", organizationId) '
        'VALUES ("p1", "서정연", NULL, NULL, NULL, NULL, "org1")'
    )
    conn.execute(
        'INSERT INTO people (id, "이름", "소속 상위 조직", "팀(명함/메일서명)", "직급(명함/메일서명)", "담당 교육 영역", organizationId) '
        'VALUES ("p2", "김정은B", "HQ", NULL, NULL, NULL, "org1")'
    )
    conn.commit()
    conn.close()


def _insert_deal(conn, row):
    conn.execute(
        'INSERT INTO deal (id, organizationId, peopleId, "이름", "담당자", "상태", "성사 가능성", "금액", "예상 체결액", "수주 예정일", '
        '"계약 체결일", "수강시작일", "수강종료일", "과정포맷", "카테고리", "코스 ID", "(온라인)입과 주기", "(온라인)입과 첫 회차", '
        '"강사 이름1", "강사비1", "제안서 작성 여부", "업로드 제안서명", "생성 날짜") '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )


def _base_deal(
    deal_id: str,
    owner: str,
    status: str,
    deal_name: str = "테스트딜",
    created: str = "2025-01-10",
):
    return (
        deal_id,
        "org1",
        "p1",
        deal_name,
        f'["{owner}"]',
        status,
        "확정",
        "1000",  # 금액 채워 R2 방지
        "0",
        "2025-02-01",
        "2025-02-01",
        "2025-02-10",
        "2025-02-15",
        "출강",
        "기타",
        "CID",
        "",
        "",
        "강사A",
        "100",
        "Y",
        "UPLD",
        created,
    )


class TestQcR13R17Hidden(unittest.TestCase):
    def test_r13_won_triggers(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            _build_base_db(Path(tmp.name))
            conn = sqlite3.connect(tmp.name)
            # upper_org missing -> meta 결측
            _insert_deal(conn, _base_deal("d1", "서정연", "Won"))
            conn.commit()
            conn.close()

            res = db.get_qc_deal_errors_summary(team="all", db_path=Path(tmp.name))
            people = res["people"]
            self.assertEqual(1, people[0]["totalIssues"])
            self.assertIn("R13", people[0]["byRule"])

    def test_r13_sql_triggers(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            _build_base_db(Path(tmp.name))
            conn = sqlite3.connect(tmp.name)
            _insert_deal(conn, _base_deal("d2", "서정연", "SQL"))
            conn.commit()
            conn.close()

            res = db.get_qc_deal_errors_summary(team="all", db_path=Path(tmp.name))
            people = res["people"]
            self.assertEqual(1, people[0]["totalIssues"])
            self.assertIn("R13", people[0]["byRule"])

    def test_r13_month_exception(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            _build_base_db(Path(tmp.name))
            conn = sqlite3.connect(tmp.name)
            _insert_deal(conn, _base_deal("d3", "김정은B", "Won", deal_name="3월 테스트딜"))
            conn.commit()
            conn.close()

            res = db.get_qc_deal_errors_summary(team="all", db_path=Path(tmp.name))
            # exception: total issues should be 0
            self.assertEqual(0, sum(p["totalIssues"] for p in res["people"]))

    def test_r17_hidden_not_exposed(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            _build_base_db(Path(tmp.name))
            conn = sqlite3.connect(tmp.name)
            _insert_deal(conn, _base_deal("d4", "서정연", "Lost"))
            conn.commit()
            conn.close()

            # public API should hide R17
            res = db.get_qc_deal_errors_summary(team="all", db_path=Path(tmp.name))
            self.assertEqual(0, sum(p["totalIssues"] for p in res["people"]))
            self.assertNotIn("R17", {r["code"] for r in res["rules"]})

            person = db.get_qc_deal_errors_for_owner(team="all", owner="서정연", db_path=Path(tmp.name))
            codes = [c for item in person.get("items", []) for c in item.get("issueCodes", [])]
            self.assertNotIn("R17", codes)

            # internal raw compute should still contain R17
            raw = db._qc_compute(team="all", db_path=Path(tmp.name), include_hidden=True)
            raw_codes = [c for item in raw["details_by_owner"].get("서정연", []) for c in item.get("issueCodes", [])]
            self.assertIn("R17", raw_codes)


if __name__ == "__main__":
    unittest.main()

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from dashboard.server import database as db
from dashboard.server.database import _clean_form_memo


def build_sample_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE organization (id TEXT, "이름" TEXT, "기업 규모" TEXT, "업종" TEXT)')
    conn.execute('INSERT INTO organization VALUES ("org1","조직1","대기업","테스트")')

    conn.execute(
        'CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "소속 상위 조직" TEXT, '
        '"팀(명함/메일서명)" TEXT, "직급(명함/메일서명)" TEXT, "담당 교육 영역" TEXT, "제출된 웹폼 목록" TEXT)'
    )
    webforms_json = json.dumps(
        [
            {"id": "wf-1", "name": "폼1"},
            {"id": "wf-2", "name": "폼2"},
            {"id": "wf-missing", "name": "폼X"},
        ]
    )
    conn.execute(
        'INSERT INTO people VALUES ("p1","org1","사람1","상위A","팀A","직급A","영역A",?)',
        (webforms_json,),
    )

    conn.execute(
        'CREATE TABLE deal (id TEXT, peopleId TEXT, organizationId TEXT, "이름" TEXT, "팀" TEXT, "담당자" TEXT, '
        '"상태" TEXT, "성사 가능성" TEXT, "수주 예정일" TEXT, "예상 체결액" TEXT, '
        '"LOST 확정일" TEXT, "이탈 사유" TEXT, "과정포맷" TEXT, "카테고리" TEXT, '
        '"계약 체결일" TEXT, "금액" TEXT, "수강시작일" TEXT, "수강종료일" TEXT, "Net(%)" TEXT, "생성 날짜" TEXT)'
    )
    conn.execute(
        'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            "d1",
            "p1",
            "org1",
            "딜1",
            "팀A",
            json.dumps({"name": "담당자1"}),
            "Won",
            None,
            None,
            None,
            None,
            None,
            "포맷",
            "카테고리",
            "2025-01-02",
            "100",
            None,
            None,
            None,
            "2025-01-01",
        ),
    )

    conn.execute(
        "CREATE TABLE memo (id TEXT, dealId TEXT, peopleId TEXT, organizationId TEXT, text TEXT, createdAt TEXT)"
    )
    conn.execute(
        "INSERT INTO memo VALUES (?,?,?,?,?,?)",
        (
            "m1",
            None,
            "p1",
            "org1",
            "- 고객 이름 : 왕철순\n- 고객 이메일 : test@example.com\n- 고객 전화 : 01012345678\n- 회사 이름 : LG유플러스\n- 고객 utm_source : email\n",
            "2025-01-01",
        ),
    )
    conn.execute(
        "INSERT INTO memo VALUES (?,?,?,?,?,?)",
        (
            "m2",
            None,
            "p1",
            "org1",
            "(단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청)\n- 고객 utm_source : email\n",
            "2025-01-02",
        ),
    )

    conn.execute(
        "CREATE TABLE webform_history (id TEXT, peopleId TEXT, organizationId TEXT, dealId TEXT, leadId TEXT, contents TEXT, createdAt TEXT, webFormId TEXT)"
    )
    conn.executemany(
        "INSERT INTO webform_history VALUES (?,?,?,?,?,?,?,?)",
        [
            ("h1", "p1", "org1", None, None, None, "2025-01-15T12:00:00Z", "wf-1"),
            ("h2", "p1", "org1", None, None, None, "2025-01-15T12:00:00Z", "wf-1"),
            ("h3", "p1", "org1", None, None, None, "2025-01-10T09:00:00Z", "wf-2"),
            ("h4", "p1", "org1", None, None, None, "2025-02-01T09:00:00Z", "wf-2"),
        ],
    )
    conn.commit()
    conn.close()


class WonGroupsWebformDateTest(TestCase):
    def test_webforms_include_history_dates_and_clean_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            build_sample_db(db_path)

            result = db.get_won_groups_json("org1", db_path=db_path)
            groups = result["groups"]
            self.assertEqual(len(groups), 1)
            people = groups[0]["people"]
            self.assertEqual(len(people), 1)

            webforms = {entry["name"]: entry for entry in people[0]["webforms"]}
            self.assertEqual(webforms["폼1"]["date"], "2025-01-15")
            self.assertEqual(webforms["폼2"]["date"], ["2025-01-10", "2025-02-01"])
            self.assertEqual(webforms["폼X"]["date"], "날짜 확인 불가")
            for entry in webforms.values():
                self.assertNotIn("id", entry)

            memos = people[0]["memos"]
            clean_list = [m["cleanText"] for m in memos if "cleanText" in m]
            self.assertEqual(len(clean_list), 2)
            # First memo keeps non-dropped keys
            self.assertIn("고객이름", clean_list[0])
            self.assertIn("고객이메일", clean_list[0])
            self.assertNotIn("고객전화", clean_list[0])
            self.assertNotIn("utm_source", clean_list[0])
            # Special phrase -> empty string
            self.assertEqual(clean_list[1], "")

    def test_clean_form_memo_preprocessing(self) -> None:
        # utm required -> no cleanText
        no_utm = "- 고객 이름 : 홍길동\n- 고객 이메일 : a@b.com\n- 고객 전화 : 01012345678\n"
        self.assertIsNone(_clean_form_memo(no_utm))

        # drop keys removed, lines merged, utm present
        merged = "- 고객 이름 : 홍길동\n- 고객 이메일 : a@b.com\n- 고객 전화 : 01012345678\n- 회사 업종 : IT/정보통신업\n- 고객 utm_source : email\n추가 줄\n"
        parsed = _clean_form_memo(merged)
        self.assertIsNotNone(parsed)
        if parsed is not None:
            self.assertIn("고객이름", parsed)
            self.assertIn("고객이메일", parsed)
            self.assertNotIn("고객전화", parsed)
            self.assertNotIn("회사업종", parsed)
            self.assertNotIn("utm_source", parsed)
            self.assertIn("추가 줄" in " ".join(parsed.values()), True)

        # special phrase forces empty string
        special = "(단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청)\n- 고객 utm_source : email\n"
        self.assertEqual(_clean_form_memo(special), "")

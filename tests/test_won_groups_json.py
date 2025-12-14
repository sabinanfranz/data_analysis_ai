import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from dashboard.server import database as db
from dashboard.server.database import _clean_form_memo
from dashboard.server.json_compact import compact_won_groups_json


def build_sample_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        'CREATE TABLE organization (id TEXT, "이름" TEXT, "기업 규모" TEXT, "업종" TEXT, '
        '"업종 구분(대)" TEXT, "업종 구분(중)" TEXT)'
    )
    conn.execute('INSERT INTO organization VALUES ("org1","조직1","대기업","테스트","금융","보험")')

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
            "2025-01-01T11:00:00",
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
            "2025-01-02 10:00:00",
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
            ("h4", "p1", "org1", None, None, None, "2025-02-01 09:00:00", "wf-2"),
        ],
    )
    conn.commit()
    conn.close()


def build_compact_sample_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        'CREATE TABLE organization (id TEXT, "이름" TEXT, "기업 규모" TEXT, "업종" TEXT, '
        '"업종 구분(대)" TEXT, "업종 구분(중)" TEXT)'
    )
    conn.execute('INSERT INTO organization VALUES ("org1","조직1","대기업","테스트","금융","보험")')

    conn.execute(
        'CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "소속 상위 조직" TEXT, '
        '"팀(명함/메일서명)" TEXT, "직급(명함/메일서명)" TEXT, "담당 교육 영역" TEXT, "제출된 웹폼 목록" TEXT)'
    )
    conn.execute(
        'INSERT INTO people VALUES ("p1","org1","사람1","상위A","고객팀","직급A","영역A","[]")'
    )
    conn.execute(
        'INSERT INTO people VALUES ("p2","org1","사람2","상위A","고객팀","직급B","영역B","[]")'
    )

    conn.execute(
        'CREATE TABLE deal (id TEXT, peopleId TEXT, organizationId TEXT, "이름" TEXT, "팀" TEXT, "담당자" TEXT, '
        '"상태" TEXT, "성사 가능성" TEXT, "수주 예정일" TEXT, "예상 체결액" TEXT, '
        '"LOST 확정일" TEXT, "이탈 사유" TEXT, "과정포맷" TEXT, "카테고리" TEXT, '
        '"계약 체결일" TEXT, "금액" TEXT, "수강시작일" TEXT, "수강종료일" TEXT, "Net(%)" TEXT, "생성 날짜" TEXT)'
    )
    deals = [
        (
            "d1",
            "p1",
            "org1",
            "딜1",
            json.dumps([{"id": "t1", "name": "교육1팀"}]),
            json.dumps({"name": "오너1"}),
            "Won",
            None,
            None,
            None,
            None,
            None,
            "구독제(온라인)",
            "카테고리X",
            "2025-01-05",
            "100",
            None,
            None,
            None,
            "2024-12-31",
        ),
        (
            "d2",
            "p1",
            "org1",
            "딜2",
            json.dumps([{"id": "t1", "name": "교육1팀", "extra": "drop"}]),
            json.dumps({"name": "오너1"}),
            "Won",
            None,
            None,
            None,
            None,
            None,
            "집합교육",
            "카테고리X",
            "2024-03-10",
            "200",
            None,
            None,
            None,
            "2024-02-01",
        ),
        (
            "d3",
            "p2",
            "org1",
            "딜3",
            json.dumps({"id": "t1", "name": "교육1팀"}),
            json.dumps({"name": "오너1"}),
            "Won",
            None,
            None,
            None,
            None,
            None,
            "집합교육",
            "카테고리X",
            "2023-07-01",
            "300",
            None,
            None,
            None,
            "2023-01-01",
        ),
        (
            "d4",
            "p2",
            "org1",
            "딜4",
            "bad-json",
            json.dumps({"name": "오너1"}),
            "Lost",
            None,
            None,
            None,
            None,
            None,
            "집합교육",
            "카테고리X",
            "2025-06-01",
            "50",
            None,
            None,
            None,
            "2025-03-03",
        ),
    ]
    conn.executemany('INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', deals)

    conn.execute(
        "CREATE TABLE memo (id TEXT, dealId TEXT, peopleId TEXT, organizationId TEXT, text TEXT, createdAt TEXT)"
    )
    conn.execute(
        "CREATE TABLE webform_history (id TEXT, peopleId TEXT, organizationId TEXT, dealId TEXT, leadId TEXT, contents TEXT, createdAt TEXT, webFormId TEXT)"
    )
    conn.commit()
    conn.close()


class WonGroupsWebformDateTest(TestCase):
    def test_webforms_include_history_dates_and_clean_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            build_sample_db(db_path)

            result = db.get_won_groups_json("org1", db_path=db_path)
            org_meta = result["organization"]
            self.assertEqual(org_meta["industry_major"], "금융")
            self.assertEqual(org_meta["industry_mid"], "보험")
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
            self.assertEqual(len(clean_list), 1)
            # First memo keeps non-dropped keys
            self.assertIn("고객이름", clean_list[0])
            self.assertIn("고객이메일", clean_list[0])
            self.assertNotIn("고객전화", clean_list[0])
            self.assertNotIn("utm_source", clean_list[0])
            # Special phrase memo is dropped entirely
            self.assertEqual(len(memos), 1)

    def test_clean_form_memo_preprocessing(self) -> None:
        # utm required -> no cleanText
        no_utm = "- 고객 이름 : 홍길동\n- 고객 이메일 : a@b.com\n- 고객 전화 : 01012345678\n"
        self.assertIsNone(_clean_form_memo(no_utm))

        # drop keys removed, lines merged, utm present
        merged = "- 고객 이름 : 홍길동\n추가 줄\n- 고객 이메일 : a@b.com\n- 고객 전화 : 01012345678\n- 회사 업종 : IT/정보통신업\n- 고객 utm_source : email\n"
        parsed = _clean_form_memo(merged)
        self.assertIsNotNone(parsed)
        if parsed is not None:
            self.assertIn("고객이름", parsed)
            self.assertIn("고객이메일", parsed)
            self.assertNotIn("고객전화", parsed)
            self.assertNotIn("회사업종", parsed)
            self.assertNotIn("utm_source", parsed)
            self.assertIn("추가 줄", parsed["고객이름"])

        # marketing consent only should still trigger cleanText and drop the field
        marketing_only = "- 고객 이름 : 김민수\n- 고객 마케팅 수신 동의 : 동의함\n- 회사 업종 : 제조\n- ATD's Privacy Notice : yes\n- SkyHive's Privacy Policy : ok\n- 고객 이메일 : foo@bar.com\n"
        parsed_marketing = _clean_form_memo(marketing_only)
        self.assertIsNotNone(parsed_marketing)
        if parsed_marketing is not None:
            self.assertIn("고객이름", parsed_marketing)
            self.assertIn("고객이메일", parsed_marketing)
            self.assertNotIn("고객마케팅수신동의", parsed_marketing)
            self.assertNotIn("ATD'sPrivacyNotice", parsed_marketing)
            self.assertNotIn("SkyHive'sPrivacyPolicy", parsed_marketing)
            self.assertNotIn("회사업종", parsed_marketing)

        # special phrase forces empty string
        special = "(단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청)\n- 고객 utm_source : email\n"
        self.assertEqual(_clean_form_memo(special), "")


class WonGroupsCompactTest(TestCase):
    def test_compact_transforms_people_team_and_prunes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            build_compact_sample_db(db_path)

            raw = db.get_won_groups_json("org1", db_path=db_path)
            compact = compact_won_groups_json(raw)

            self.assertEqual(compact["schema_version"], "won-groups-json/compact-v1")
            self.assertIn("summary", compact["organization"])

            group = compact["groups"][0]
            deals = {d["id"]: d for d in group["deals"]}

            self.assertNotIn("people", deals["d1"])
            self.assertEqual(deals["d1"]["people_id"], "p1")
            self.assertNotIn("team", deals["d1"])
            self.assertIn("day1_teams", deals["d1"])
            self.assertEqual(deals["d1"]["day1_teams"][0]["name"], "교육1팀")

            self.assertNotIn("team", deals["d2"])
            self.assertIn("day1_teams_raw", deals["d4"])

            people = {p["id"]: p for p in group["people"]}
            self.assertNotIn("memos", people["p1"])
            self.assertNotIn("memos", deals["d2"])
            self.assertNotIn("webforms", people["p2"])

    def test_compact_defaults_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            build_compact_sample_db(db_path)

            raw = db.get_won_groups_json("org1", db_path=db_path)
            compact = compact_won_groups_json(raw)

            group = compact["groups"][0]
            defaults = group["deal_defaults"]
            self.assertEqual(defaults.get("category"), "카테고리X")
            self.assertEqual(defaults.get("owner"), "오너1")
            for deal in group["deals"]:
                self.assertNotIn("category", deal)
                self.assertNotIn("owner", deal)

            summary = group["counterparty_summary"]
            self.assertEqual(summary["won_amount_by_year"]["2023"], 300.0)
            self.assertEqual(summary["won_amount_by_year"]["2024"], 200.0)
            self.assertEqual(summary["won_amount_by_year"]["2025"], 100.0)
            self.assertEqual(summary["won_amount_online_by_year"]["2025"], 100.0)
            self.assertEqual(summary["won_amount_offline_by_year"]["2024"], 200.0)

            org_summary = compact["organization"]["summary"]
            self.assertEqual(org_summary["won_amount_by_year"]["2025"], 100.0)
            self.assertEqual(org_summary["won_amount_offline_by_year"]["2023"], 300.0)

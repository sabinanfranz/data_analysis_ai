import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from build_org_mindmap import build_hierarchy, load_data, render_html


class MindmapDataTest(TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "db.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        # Minimal schemas with the columns the extractor touches.
        self.conn.execute('CREATE TABLE organization (id TEXT, "이름" TEXT, "업종" TEXT, "팀" TEXT, "담당자" TEXT)')
        self.conn.execute(
            'CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "직급/직책" TEXT, "이메일" TEXT, "전화" TEXT, "고객 상태" TEXT)'
        )
        self.conn.execute(
            'CREATE TABLE deal (id TEXT, peopleId TEXT, organizationId TEXT, "이름" TEXT, "상태" TEXT, "금액" REAL, "예상 체결액" REAL, "마감일" TEXT, "수주 예정일" TEXT)'
        )
        self.conn.execute(
            'CREATE TABLE memo (id TEXT, dealId TEXT, text TEXT, createdAt TEXT, updatedAt TEXT, ownerId TEXT)'
        )
        self.conn.executemany(
            'INSERT INTO organization (id, "이름", "업종", "팀", "담당자") VALUES (?, ?, ?, ?, ?)',
            [("org1", "조직A", "IT", "팀A", "담당자A")],
        )
        self.conn.executemany(
            'INSERT INTO people (id, organizationId, "이름", "직급/직책", "이메일", "전화", "고객 상태") VALUES (?, ?, ?, ?, ?, ?, ?)',
            [("p1", "org1", "홍길동", "매니저", "a@example.com", "010", "활성")],
        )
        self.conn.executemany(
            'INSERT INTO deal (id, peopleId, organizationId, "이름", "상태", "금액", "예상 체결액", "마감일", "수주 예정일") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [("d1", "p1", "org1", "딜1", "진행", 1000, 1200, "2024-12-31", "2024-12-01")],
        )
        self.conn.executemany(
            'INSERT INTO memo (id, dealId, text, createdAt, updatedAt, ownerId) VALUES (?, ?, ?, ?, ?, ?)',
            [("m1", "d1", "첫 메모", "2024-01-01", "2024-01-02", "owner")],
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def test_load_and_hierarchy_structure(self) -> None:
        raw = load_data(self.db_path, org_id=None, org_name=None, limit_orgs=None)
        self.assertEqual(len(raw["organizations"]), 1)
        self.assertEqual(len(raw["people"]), 1)
        self.assertEqual(len(raw["deals"]), 1)
        self.assertEqual(len(raw["memos"]), 1)

        hierarchy, options = build_hierarchy(raw)
        self.assertEqual(options[0]["id"], "org1")
        root = hierarchy["org1"]
        self.assertEqual(root["label"], "조직A")
        person = root["children"][0]
        self.assertEqual(person["label"], "홍길동")
        deal = person["children"][0]
        self.assertEqual(deal["label"], "딜1")
        memo = deal["children"][0]
        self.assertEqual(memo["meta"]["전체 메모"], "첫 메모")

    def test_render_html_contains_data(self) -> None:
        raw = load_data(self.db_path, org_id=None, org_name=None, limit_orgs=None)
        hierarchy, options = build_hierarchy(raw)
        out_path = Path(self.tmpdir.name) / "out.html"
        render_html(hierarchy, options, options[0]["id"], out_path)
        text = out_path.read_text(encoding="utf-8")
        # Basic sanity: embedded data and option label present.
        self.assertIn("DATA_BY_ORG", text)
        self.assertIn("조직A", text)
        self.assertIn("홍길동", text)

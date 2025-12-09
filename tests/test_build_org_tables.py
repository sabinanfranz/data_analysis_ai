import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from build_org_tables import build_maps, load_data, render_html


class OrgTablesTest(TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "db.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute('CREATE TABLE organization (id TEXT, "이름" TEXT, "업종" TEXT, "팀" TEXT, "담당자" TEXT, "전화" TEXT)')
        self.conn.execute(
            'CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "직급/직책" TEXT, "이메일" TEXT, "전화" TEXT, "고객 상태" TEXT)'
        )
        self.conn.execute(
            'CREATE TABLE deal (id TEXT, peopleId TEXT, organizationId TEXT, "이름" TEXT, "상태" TEXT, "금액" REAL, "예상 체결액" REAL, "마감일" TEXT, "수주 예정일" TEXT)'
        )
        self.conn.execute(
            'CREATE TABLE memo (id TEXT, dealId TEXT, peopleId TEXT, organizationId TEXT, text TEXT, createdAt TEXT, updatedAt TEXT, ownerId TEXT)'
        )
        self.conn.executemany(
            'INSERT INTO organization (id, "이름", "업종", "팀", "담당자", "전화") VALUES (?, ?, ?, ?, ?, ?)',
            [("org1", "조직A", "IT", "팀A", "담당자A", "010")],
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
            'INSERT INTO memo (id, dealId, peopleId, organizationId, text, createdAt, updatedAt, ownerId) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            [
                ("m1", "d1", None, "org1", "딜 메모", "2024-01-01", "2024-01-02", "owner"),
                ("m2", None, "p1", "org1", "사람 메모", "2024-02-01", "2024-02-02", "owner2"),
                ("m3", None, None, "org1", "조직 메모", "2024-03-01", "2024-03-02", "owner3"),
            ],
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def test_load_build_maps(self) -> None:
        raw = load_data(self.db_path, org_id=None, org_name=None, limit_orgs=None)
        maps = build_maps(raw)
        self.assertIn("org1", maps["people_by_org"])
        self.assertIn("p1", maps["deals_by_person"])
        self.assertIn("d1", maps["memos_by_deal"])
        self.assertIn("p1", maps["memos_by_person"])
        self.assertIn("org1", maps["memos_by_org"])
        self.assertEqual(maps["people_by_org"]["org1"][0]["_deal_count"], 1)
        self.assertEqual(maps["organizations"][0]["name"], "조직A")

    def test_render_html_embeds_payload(self) -> None:
        raw = load_data(self.db_path, org_id=None, org_name=None, limit_orgs=None)
        maps = build_maps(raw)
        out_path = Path(self.tmpdir.name) / "org_tables.html"
        render_html(maps, default_org="org1", output_path=out_path)
        text = out_path.read_text(encoding="utf-8")
        self.assertIn("조직A", text)
        self.assertIn("홍길동", text)
        self.assertIn("딜1", text)
        self.assertIn("딜 메모", text)
        self.assertIn("사람 메모", text)
        self.assertIn("조직 메모", text)

    def test_filter_out_org_without_people_or_deal(self) -> None:
        # Insert an org with no people and no deals -> should be filtered out
        self.conn.execute('INSERT INTO organization (id, "이름") VALUES (?, ?)', ("org2", "빈조직"))
        self.conn.commit()
        raw = load_data(self.db_path, org_id=None, org_name=None, limit_orgs=None)
        maps = build_maps(raw)
        ids = [o["id"] for o in maps["organizations"]]
        self.assertIn("org1", ids)
        self.assertNotIn("org2", ids)

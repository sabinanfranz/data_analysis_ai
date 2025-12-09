#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def fetch_rows(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...]) -> List[sqlite3.Row]:
    cur = conn.execute(sql, params)
    return cur.fetchall()


def load_data(
    db_path: Path,
    org_id: Optional[str],
    org_name: Optional[str],
    limit_orgs: Optional[int],
) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Force temp storage to memory to avoid OS temp dir write restrictions during ORDER BY.
    conn.execute("PRAGMA temp_store=MEMORY;")

    org_where: List[str] = []
    org_params: List[Any] = []
    if org_id:
        org_where.append("id = ?")
        org_params.append(org_id)
    elif org_name:
        org_where.append('LOWER("이름") LIKE ?')
        org_params.append(f"%{org_name.lower()}%")

    org_sql = (
        'SELECT id, COALESCE("이름", id) as name, "업종" as industry, "팀" as team, "담당자" as owner, "전화" as phone, "기업 규모" as size '
        "FROM organization"
    )
    if org_where:
        org_sql += " WHERE " + " AND ".join(org_where)
    org_sql += " ORDER BY name"
    if limit_orgs is not None:
        org_sql += " LIMIT ?"
        org_params.append(limit_orgs)

    org_rows = fetch_rows(conn, org_sql, tuple(org_params))
    if not org_rows:
        raise SystemExit("No organizations matched the filter.")

    org_ids = [row["id"] for row in org_rows]

    def placeholders(seq: List[Any]) -> str:
        return ",".join("?" for _ in seq)

    people_rows: List[sqlite3.Row] = []
    if org_ids:
        people_sql = (
            'SELECT id, organizationId, COALESCE("이름", id) as name, '
            '"직급/직책" as title, "이메일" as email, "전화" as phone, "고객 상태" as status '
            "FROM people WHERE organizationId IN ({})"
        ).format(placeholders(org_ids))
        people_rows = fetch_rows(conn, people_sql, tuple(org_ids))

    people_ids = [row["id"] for row in people_rows]

    deal_rows: List[sqlite3.Row] = []
    if people_ids:
        deal_sql = (
            'SELECT id, peopleId, organizationId, COALESCE("이름", id) as name, "상태" as status, '
            '"금액" as amount, "예상 체결액" as expected_amount, "마감일" as deadline, "수주 예정일" as expected_date '
            "FROM deal WHERE peopleId IN ({})"
        ).format(placeholders(people_ids))
        deal_rows = fetch_rows(conn, deal_sql, tuple(people_ids))

    deal_ids = [row["id"] for row in deal_rows]

    memo_rows: List[sqlite3.Row] = []
    if deal_ids:
        memo_sql = (
            "SELECT id, dealId, peopleId, organizationId, text, createdAt, updatedAt, ownerId "
            "FROM memo WHERE dealId IN ({})"
        ).format(placeholders(deal_ids))
        memo_rows = fetch_rows(conn, memo_sql, tuple(deal_ids))

    # Org-level and person-level memos (no deal)
    org_memo_rows: List[sqlite3.Row] = []
    if org_ids:
        org_memo_sql = (
            "SELECT id, organizationId, peopleId, text, createdAt, updatedAt, ownerId "
            "FROM memo WHERE organizationId IN ({})"
        ).format(placeholders(org_ids))
        org_memo_rows = fetch_rows(conn, org_memo_sql, tuple(org_ids))

    return {
        "organizations": org_rows,
        "people": people_rows,
        "deals": deal_rows,
        "memos": memo_rows,
        "org_memos": org_memo_rows,
    }


def build_maps(raw: Dict[str, List[sqlite3.Row]]) -> Dict[str, Any]:
    people_by_org: Dict[str, List[Dict[str, Any]]] = {}
    for row in raw["people"]:
        org_id = row["organizationId"]
        people_by_org.setdefault(org_id, []).append(dict(row))

    deals_by_person: Dict[str, List[Dict[str, Any]]] = {}
    for row in raw["deals"]:
        deals_by_person.setdefault(row["peopleId"], []).append(dict(row))

    memos_by_deal: Dict[str, List[Dict[str, Any]]] = {}
    for row in raw["memos"]:
        memos_by_deal.setdefault(row["dealId"], []).append(dict(row))

    memos_by_person: Dict[str, List[Dict[str, Any]]] = {}
    memos_by_org: Dict[str, List[Dict[str, Any]]] = {}
    for row in raw.get("org_memos", []):
        memo_dict = dict(row)
        org_id = memo_dict.get("organizationId")
        person_id = memo_dict.get("peopleId")
        deal_id = memo_dict.get("dealId")
        if deal_id:  # skip, already in deal memos
            continue
        if person_id:
            memos_by_person.setdefault(person_id, []).append(memo_dict)
        elif org_id:
            memos_by_org.setdefault(org_id, []).append(memo_dict)

    # Annotate people with deal counts for sorting/rendering.
    person_deal_counts: Dict[str, int] = {}
    for person_id, deals in deals_by_person.items():
        person_deal_counts[person_id] = len(deals)
    people_by_org = {
        org_id: [
            {**p, "_deal_count": person_deal_counts.get(p["id"], 0)} for p in people
        ]
        for org_id, people in people_by_org.items()
    }

    org_list = [dict(row) for row in raw["organizations"]]
    # Filter out organizations without people and without deals
    filtered_orgs = []
    for org in org_list:
        org_id = org["id"]
        has_people = bool(people_by_org.get(org_id))
        has_deals = False
        for person in people_by_org.get(org_id, []):
            if deals_by_person.get(person["id"]):
                has_deals = True
                break
        if has_people or has_deals:
            filtered_orgs.append(org)

    if not filtered_orgs:
        raise SystemExit("No organizations with people or deals were found for the given filter.")
    return {
        "organizations": filtered_orgs,
        "people_by_org": people_by_org,
        "deals_by_person": deals_by_person,
        "memos_by_deal": memos_by_deal,
        "memos_by_person": memos_by_person,
        "memos_by_org": memos_by_org,
    }


def render_html(
    data: Dict[str, Any],
    default_org: str,
    output_path: Path,
) -> None:
    org_options = [
        {
            "id": org["id"],
            "label": org.get("name") or org["id"],
            "team": org.get("team"),
            "owner": org.get("owner"),
            "size": org.get("size"),
        }
        for org in data["organizations"]
    ]
    payload = {
        "orgOptions": org_options,
        "peopleByOrg": data["people_by_org"],
        "dealsByPerson": data["deals_by_person"],
        "memosByDeal": data["memos_by_deal"],
        "memosByPerson": data["memos_by_person"],
        "memosByOrg": data["memos_by_org"],
    }
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>조직/People/Deal/Memo 테이블 탐색기</title>
  <style>
    :root {{
      --bg: #0f172a;
      --panel: #0b1220;
      --border: #1f2937;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-2: #facc15;
      --accent-3: #22c55e;
      --accent-4: #c084fc;
      --shadow: 0 12px 40px rgba(0,0,0,0.35);
      --error: #f87171;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: 'Inter', 'Pretendard', -apple-system, 'Segoe UI', sans-serif;
      background: radial-gradient(circle at 15% 20%, rgba(56, 189, 248, 0.08), transparent 28%),
                  radial-gradient(circle at 85% 10%, rgba(192, 132, 252, 0.08), transparent 25%),
                  var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      padding: 16px;
      gap: 12px;
    }}
    header {{
      display: flex;
      flex-direction: column;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px 16px;
      box-shadow: var(--shadow);
      gap: 10px;
    }}
    .control-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      width: 100%;
      justify-content: space-between;
    }}
    h1 {{ margin: 0; font-size: 18px; }}
    select, button {{
      background: #0f182a;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
    }}
    button:hover, select:focus {{ border-color: var(--accent); outline: none; }}
    .breadcrumb {{ display: flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); }}
    .org-grid {{
      flex: 1;
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      grid-template-rows: 1fr 1fr 1fr;
      gap: 10px;
      min-height: 0;
      height: calc(100vh - 170px);
    }}
    .col {{
      display: grid;
      grid-template-rows: 1fr 1fr 1fr;
      gap: 10px;
      min-height: 0;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px;
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .card h2 {{
      margin: 0 0 10px 0;
      font-size: 16px;
      color: var(--muted);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    h3 {{ margin: 0 0 6px 0; color: var(--muted); font-size: 14px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 8px;
      border-bottom: 1px solid var(--border);
    }}
    th {{
      text-align: left;
      color: var(--muted);
      font-weight: 600;
      letter-spacing: 0.01em;
    }}
    tr:hover {{ background: rgba(56, 189, 248, 0.08); }}
    tr.active {{ background: rgba(56, 189, 248, 0.15); }}
    .table-wrap {{
      flex: 1;
      overflow: auto;
      min-height: 0;
    }}
    .memo-split {{
      display: grid;
      grid-template-rows: 1fr 1fr;
      gap: 8px;
      min-height: 0;
    }}
    .memo-block {{
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .muted {{ color: var(--muted); }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: rgba(56, 189, 248, 0.15); color: var(--accent); }}
    @media (max-width: 1024px) {{
      .org-grid {{
        grid-template-columns: 1fr;
        grid-template-rows: auto;
        height: auto;
      }}
      #orgMemoCard {{
        grid-column: 1 / 2;
        grid-row: auto;
      }}
      .col {{
        grid-template-rows: repeat(3, minmax(240px, auto));
      }}
    }}
    @media (max-width: 768px) {{
      th, td {{ padding: 6px; font-size: 12px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="control-row" style="justify-content: space-between;">
      <h1>조직/People/Deal/Memo 테이블 탐색기</h1>
      <div class="control-row" style="flex:1; justify-content:flex-end;">
        <label style="color:var(--muted); font-size:13px;">기업 규모</label>
        <select id="sizeSelect" aria-label="Select size"></select>
        <label style="color:var(--muted); font-size:13px;">회사</label>
        <select id="orgSelect" aria-label="Select organization"></select>
        <button id="resetBtn" type="button">선택 초기화</button>
      </div>
    </div>
  </header>
  <div class="breadcrumb" id="breadcrumb">
    <span>경로:</span> <span id="crumb-org">-</span> <span>›</span> <span id="crumb-person">-</span> <span>›</span> <span id="crumb-deal">-</span>
  </div>
  <div id="org-tables-root" class="org-grid">
    <section class="card memo-card" id="orgMemoCard" style="grid-column: 1 / 2; grid-row: 1 / 4;">
      <h2>회사 메모</h2>
      <div class="muted" id="orgMemoHint">회사를 선택하세요.</div>
      <div class="table-wrap">
        <table id="orgMemoTable"></table>
      </div>
    </section>

    <div class="col col-with" style="grid-column: 2 / 3; grid-row: 1 / 4;">
      <section class="card cell">
        <h2>People (딜 있음)</h2>
        <div class="muted" id="peopleWithHint">회사를 선택하세요.</div>
        <div class="table-wrap">
          <table id="peopleWithTable"></table>
        </div>
      </section>
      <section class="card cell">
        <h2>Deals</h2>
        <div class="muted" id="dealWithHint">사람을 선택하세요.</div>
        <div class="table-wrap">
          <table id="dealWithTable"></table>
        </div>
      </section>
      <section class="card cell">
        <div class="memo-split">
          <div class="memo-block">
            <h3>People 메모</h3>
            <div class="muted" id="personMemoWithHint">사람을 선택하세요.</div>
            <div class="table-wrap">
              <table id="personMemoWithTable"></table>
            </div>
          </div>
          <div class="memo-block">
            <h3>Deal 메모</h3>
            <div class="muted" id="dealMemoWithHint">딜을 선택하세요.</div>
            <div class="table-wrap">
              <table id="dealMemoWithTable"></table>
            </div>
          </div>
        </div>
      </section>
    </div>

    <div class="col col-without" style="grid-column: 3 / 4; grid-row: 1 / 4;">
      <section class="card cell">
        <h2>People (딜 없음)</h2>
        <div class="muted" id="peopleWithoutHint">회사를 선택하세요.</div>
        <div class="table-wrap">
          <table id="peopleWithoutTable"></table>
        </div>
      </section>
      <section class="card cell">
        <h2>Deals</h2>
        <div class="muted" id="dealWithoutHint">사람을 선택하세요.</div>
        <div class="table-wrap">
          <table id="dealWithoutTable"></table>
        </div>
      </section>
      <section class="card cell">
        <div class="memo-split">
          <div class="memo-block">
            <h3>People 메모</h3>
            <div class="muted" id="personMemoWithoutHint">사람을 선택하세요.</div>
            <div class="table-wrap">
              <table id="personMemoWithoutTable"></table>
            </div>
          </div>
          <div class="memo-block">
            <h3>Deal 메모</h3>
            <div class="muted" id="dealMemoWithoutHint">딜을 선택하세요.</div>
            <div class="table-wrap">
              <table id="dealMemoWithoutTable"></table>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
  <script id="data" type="application/json">{json.dumps(payload, ensure_ascii=False)}</script>
  <script>
    const DATA = JSON.parse(document.getElementById('data').textContent);
    let sizeFilter = '대기업';
    let stateWith = {{ orgId: "{default_org}", personId: null, dealId: null }};
    let stateWithout = {{ orgId: "{default_org}", personId: null, dealId: null }};

    function setBreadcrumb() {{
      const org = stateWith.orgId || stateWithout.orgId;
      document.getElementById('crumb-org').textContent = org || '-';
      document.getElementById('crumb-person').textContent = stateWith.personId || stateWithout.personId || '-';
      document.getElementById('crumb-deal').textContent = stateWith.dealId || stateWithout.dealId || '-';
    }}

    function formatDate(val) {{
      if (!val) return '-';
      const s = String(val);
      const clean = s.split('T')[0].split(' ')[0];
      return clean || s;
    }}

    function formatAmount(val) {{
      const num = Number(val);
      if (!Number.isFinite(num)) return '-';
      return (num / 1e8).toFixed(2) + '억';
    }}

    function getFilteredOrgs() {{
      return DATA.orgOptions.filter(o => sizeFilter === '전체' || (o.size || '미분류') === sizeFilter);
    }}

    function renderSizeSelect() {{
      const sel = document.getElementById('sizeSelect');
      const sizes = Array.from(new Set(DATA.orgOptions.map(o => o.size).filter(Boolean)));
      sizes.sort();
      sizes.unshift('전체');
      if (!sizes.includes(sizeFilter)) {{
        sizeFilter = sizes.includes('대기업') ? '대기업' : (sizes[0] || '전체');
      }}
      sel.innerHTML = sizes.map(s => `<option value="${{s}}">${{s}}</option>`).join('');
      sel.value = sizeFilter;
      sel.addEventListener('change', () => {{
        sizeFilter = sel.value;
        renderOrgSelect();
        applyOrgSelection(stateWith.orgId);
      }});
    }}

    function applyOrgSelection(orgId) {{
      stateWith = {{ orgId, personId: null, dealId: null }};
      stateWithout = {{ orgId, personId: null, dealId: null }};
      renderOrgMemos();
      renderPeopleWith();
      renderPeopleWithout();
      renderDealsWith();
      renderDealsWithout();
      renderPersonMemosWith();
      renderPersonMemosWithout();
      renderDealMemosWith();
      renderDealMemosWithout();
      setBreadcrumb();
    }}

    function renderOrgSelect() {{
      const sel = document.getElementById('orgSelect');
      const filtered = getFilteredOrgs();
      if (!filtered.length) {{
        sel.innerHTML = '<option value="">해당 규모 회사 없음</option>';
        applyOrgSelection(null);
        return;
      }}
      if (!filtered.find(o => o.id === stateWith.orgId)) {{
        stateWith.orgId = filtered[0].id;
        stateWithout.orgId = filtered[0].id;
      }}
      sel.innerHTML = filtered
        .map(o => `<option value="${{o.id}}" ${{o.id===stateWith.orgId?'selected':''}}>${{o.label}}${{o.size ? ' (' + o.size + ')' : ''}}</option>`)
        .join('');
      sel.value = stateWith.orgId || '';
      sel.onchange = () => applyOrgSelection(sel.value);
    }}

    function renderOrgMemos() {{
      const table = document.getElementById('orgMemoTable');
      const hint = document.getElementById('orgMemoHint');
      const card = document.getElementById('orgMemoCard');
      if (!stateWith.orgId) {{
        table.innerHTML = '';
        hint.textContent = '회사를 선택하세요.';
        card.classList.remove('has-memos');
        return;
      }}
      const memos = (DATA.memosByOrg[stateWith.orgId] || []).filter(m => !m.dealId && !m.peopleId);
      if (!memos.length) {{
        table.innerHTML = '';
        hint.textContent = '회사에 직접 연결된 메모가 없습니다.';
        card.classList.remove('has-memos');
        return;
      }}
      card.classList.add('has-memos');
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>작성일</th><th>작성자</th><th>본문</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      memos.forEach(m => {{
        const text = (m.text || '').slice(0, 120) + ((m.text || '').length > 120 ? '…' : '');
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{formatDate(m.createdAt)}}</td>
          <td>${{m.ownerId || '-'}} </td>
          <td title="${{m.text || ''}}">${{text || '(내용 없음)'}} </td>
        `;
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderPeopleWith() {{
      const table = document.getElementById('peopleWithTable');
      const hint = document.getElementById('peopleWithHint');
      if (!stateWith.orgId) {{
        table.innerHTML = '';
        hint.textContent = '회사를 선택하세요.';
        return;
      }}
      const people = (DATA.peopleByOrg[stateWith.orgId] || []).filter(p => (p._deal_count || 0) > 0);
      if (!people.length) {{
        table.innerHTML = '';
        hint.textContent = '딜이 있는 사람이 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>이름</th><th>직급/직책</th><th>이메일</th><th>전화</th><th>상태</th><th>딜 개수</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      people.forEach(p => {{
        const tr = document.createElement('tr');
        if (stateWith.personId === p.id) tr.classList.add('active');
        tr.innerHTML = `
          <td>${{p.name || '-'}} </td>
          <td>${{p["직급/직책"] || p.title || '-'}} </td>
          <td>${{p.email || '-'}} </td>
          <td>${{p.phone || '-'}} </td>
          <td>${{p.status || '-'}} </td>
          <td>${{p._deal_count ?? 0}}</td>
        `;
        tr.addEventListener('click', () => {{
          stateWith.personId = p.id;
          stateWith.dealId = null;
          renderPeopleWith();
          renderDealsWith();
          renderPersonMemosWith();
          renderDealMemosWith();
          setBreadcrumb();
        }});
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderPeopleWithout() {{
      const table = document.getElementById('peopleWithoutTable');
      const hint = document.getElementById('peopleWithoutHint');
      if (!stateWithout.orgId) {{
        table.innerHTML = '';
        hint.textContent = '회사를 선택하세요.';
        return;
      }}
      const people = (DATA.peopleByOrg[stateWithout.orgId] || []).filter(p => (p._deal_count || 0) === 0);
      if (!people.length) {{
        table.innerHTML = '';
        hint.textContent = '딜 없는 사람이 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>이름</th><th>직급/직책</th><th>이메일</th><th>전화</th><th>상태</th><th>딜 개수</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      people.forEach(p => {{
        const tr = document.createElement('tr');
        if (stateWithout.personId === p.id) tr.classList.add('active');
        tr.innerHTML = `
          <td>${{p.name || '-'}} </td>
          <td>${{p["직급/직책"] || p.title || '-'}} </td>
          <td>${{p.email || '-'}} </td>
          <td>${{p.phone || '-'}} </td>
          <td>${{p.status || '-'}} </td>
          <td>${{p._deal_count ?? 0}}</td>
        `;
        tr.addEventListener('click', () => {{
          stateWithout.personId = p.id;
          stateWithout.dealId = null;
          renderPeopleWithout();
          renderDealsWithout();
          renderPersonMemosWithout();
          renderDealMemosWithout();
          setBreadcrumb();
        }});
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderDealsWith() {{
      const table = document.getElementById('dealWithTable');
      const hint = document.getElementById('dealWithHint');
      if (!stateWith.personId) {{
        table.innerHTML = '';
        hint.textContent = '사람을 선택하세요.';
        return;
      }}
      const deals = DATA.dealsByPerson[stateWith.personId] || [];
      if (!deals.length) {{
        table.innerHTML = '';
        hint.textContent = '딜이 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>이름</th><th>상태</th><th>금액(억)</th><th>예상 체결액(억)</th><th>마감일</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      deals.forEach(d => {{
        const tr = document.createElement('tr');
        if (stateWith.dealId === d.id) tr.classList.add('active');
        tr.innerHTML = `
          <td>${{d.name || '-'}} </td>
          <td>${{d.status || '-'}}${{d.status ? '' : ''}}</td>
          <td>${{formatAmount(d.amount)}}</td>
          <td>${{formatAmount(d.expected_amount)}}</td>
          <td>${{formatDate(d.deadline)}}</td>
        `;
        tr.addEventListener('click', () => {{
          stateWith.dealId = d.id;
          renderDealsWith();
          renderDealMemosWith();
          setBreadcrumb();
        }});
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderDealsWithout() {{
      const table = document.getElementById('dealWithoutTable');
      const hint = document.getElementById('dealWithoutHint');
      if (!stateWithout.personId) {{
        table.innerHTML = '';
        hint.textContent = '사람을 선택하세요.';
        return;
      }}
      const deals = DATA.dealsByPerson[stateWithout.personId] || [];
      if (!deals.length) {{
        table.innerHTML = '';
        hint.textContent = '딜이 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>이름</th><th>상태</th><th>금액(억)</th><th>예상 체결액(억)</th><th>마감일</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      deals.forEach(d => {{
        const tr = document.createElement('tr');
        if (stateWithout.dealId === d.id) tr.classList.add('active');
        tr.innerHTML = `
          <td>${{d.name || '-'}} </td>
          <td>${{d.status || '-'}}${{d.status ? '' : ''}}</td>
          <td>${{formatAmount(d.amount)}}</td>
          <td>${{formatAmount(d.expected_amount)}}</td>
          <td>${{formatDate(d.deadline)}}</td>
        `;
        tr.addEventListener('click', () => {{
          stateWithout.dealId = d.id;
          renderDealsWithout();
          renderDealMemosWithout();
          setBreadcrumb();
        }});
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderPersonMemosWith() {{
      const table = document.getElementById('personMemoWithTable');
      const hint = document.getElementById('personMemoWithHint');
      if (!stateWith.personId) {{
        table.innerHTML = '';
        hint.textContent = '사람을 선택하세요.';
        return;
      }}
      const memos = DATA.memosByPerson[stateWith.personId] || [];
      if (!memos.length) {{
        table.innerHTML = '';
        hint.textContent = '사람에 연결된 메모가 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>작성일</th><th>작성자</th><th>본문</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      memos.forEach(m => {{
        const text = (m.text || '').slice(0, 120) + ((m.text || '').length > 120 ? '…' : '');
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{formatDate(m.createdAt)}}</td>
          <td>${{m.ownerId || '-'}} </td>
          <td title="${{m.text || ''}}">${{text || '(내용 없음)'}} </td>
        `;
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderPersonMemosWithout() {{
      const table = document.getElementById('personMemoWithoutTable');
      const hint = document.getElementById('personMemoWithoutHint');
      if (!stateWithout.personId) {{
        table.innerHTML = '';
        hint.textContent = '사람을 선택하세요.';
        return;
      }}
      const memos = DATA.memosByPerson[stateWithout.personId] || [];
      if (!memos.length) {{
        table.innerHTML = '';
        hint.textContent = '사람에 연결된 메모가 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>작성일</th><th>작성자</th><th>본문</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      memos.forEach(m => {{
        const text = (m.text || '').slice(0, 120) + ((m.text || '').length > 120 ? '…' : '');
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{formatDate(m.createdAt)}}</td>
          <td>${{m.ownerId || '-'}} </td>
          <td title="${{m.text || ''}}">${{text || '(내용 없음)'}} </td>
        `;
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderDealMemosWith() {{
      const table = document.getElementById('dealMemoWithTable');
      const hint = document.getElementById('dealMemoWithHint');
      if (!stateWith.dealId) {{
        table.innerHTML = '';
        hint.textContent = '딜을 선택하세요.';
        return;
      }}
      const memos = DATA.memosByDeal[stateWith.dealId] || [];
      if (!memos.length) {{
        table.innerHTML = '';
        hint.textContent = '딜에 연결된 메모가 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>작성일</th><th>작성자</th><th>본문</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      memos.forEach(m => {{
        const text = (m.text || '').slice(0, 120) + ((m.text || '').length > 120 ? '…' : '');
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{formatDate(m.createdAt)}}</td>
          <td>${{m.ownerId || '-'}} </td>
          <td title="${{m.text || ''}}">${{text || '(내용 없음)'}} </td>
        `;
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderDealMemosWithout() {{
      const table = document.getElementById('dealMemoWithoutTable');
      const hint = document.getElementById('dealMemoWithoutHint');
      if (!stateWithout.dealId) {{
        table.innerHTML = '';
        hint.textContent = '딜을 선택하세요.';
        return;
      }}
      const memos = DATA.memosByDeal[stateWithout.dealId] || [];
      if (!memos.length) {{
        table.innerHTML = '';
        hint.textContent = '딜에 연결된 메모가 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>작성일</th><th>작성자</th><th>본문</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      memos.forEach(m => {{
        const text = (m.text || '').slice(0, 120) + ((m.text || '').length > 120 ? '…' : '');
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{formatDate(m.createdAt)}}</td>
          <td>${{m.ownerId || '-'}} </td>
          <td title="${{m.text || ''}}">${{text || '(내용 없음)'}} </td>
        `;
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    document.getElementById('resetBtn').addEventListener('click', () => {{
      stateWith.personId = null;
      stateWith.dealId = null;
      stateWithout.personId = null;
      stateWithout.dealId = null;
      renderPeopleWith();
      renderPeopleWithout();
      renderDealsWith();
      renderDealsWithout();
      renderPersonMemosWith();
      renderPersonMemosWithout();
      renderDealMemosWith();
      renderDealMemosWithout();
      setBreadcrumb();
    }});

    renderSizeSelect();
    renderOrgSelect();
    applyOrgSelection(stateWith.orgId);
    setBreadcrumb();
  </script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote table explorer to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local HTML table explorer (org -> people -> deal -> memo).")
    parser.add_argument("--db-path", default="salesmap_latest.db", help="Path to SQLite snapshot.")
    parser.add_argument("--output", default="org_tables.html", help="Output HTML file path.")
    parser.add_argument("--org-id", default=None, help="Filter to a specific organization id.")
    parser.add_argument("--org-name", default=None, help="Filter organizations by name (LIKE match, case-insensitive).")
    parser.add_argument("--limit-orgs", type=int, default=None, help="Limit number of organizations (after filter).")
    args = parser.parse_args()

    db_path = Path(args.db_path or "salesmap_latest.db")
    if not db_path.exists():
        raise SystemExit(f"DB not found at {db_path}")

    raw = load_data(db_path, args.org_id, args.org_name, args.limit_orgs)
    maps = build_maps(raw)
    default_org = maps["organizations"][0]["id"]
    render_html(maps, default_org, Path(args.output))


if __name__ == "__main__":
    main()

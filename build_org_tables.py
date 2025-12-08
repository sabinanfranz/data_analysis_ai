#!/usr/bin/env python3
import argparse
import json
import os
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
    api_config: Optional[Dict[str, str]] = None,
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
        "apiConfig": api_config or {"baseUrl": "", "token": ""},
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
      padding: 14px;
      gap: 12px;
    }}
    header {{
      display: flex;
      flex-direction: column;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 16px;
      box-shadow: var(--shadow);
      gap: 10px;
    }}
    .control-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      width: 100%;
    }}
    h1 {{ margin: 0; font-size: 18px; }}
    select, button, input {{
      background: #0f182a;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
    }}
    input[type="text"], input[type="password"] {{
      min-width: 200px;
    }}
    button:hover, select:focus, input:focus {{ border-color: var(--accent); outline: none; }}
    main {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
      gap: 12px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px;
      box-shadow: var(--shadow);
      min-height: 260px;
      display: flex;
      flex-direction: column;
    }}
    .stack {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .subgrid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      align-items: stretch;
    }}
    .memos {{
      display: grid;
      grid-template-rows: 1fr 1fr;
      gap: 8px;
      height: 100%;
    }}
    .memo-block {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 320px;
    }}
    .table-wrap.half {{
      height: 100%;
    }}
    .top-memo {{
      min-height: 80px;
      transition: height 0.3s ease;
      overflow: hidden;
    }}
    .top-memo.has-memos {{
      min-height: 220px;
    }}
    .double-row {{
      display: grid;
      grid-template-rows: 1fr 1fr;
      gap: 8px;
      height: 100%;
    }}
    .card h2 {{
      margin: 0 0 10px 0;
      font-size: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: var(--muted);
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
    .muted {{ color: var(--muted); }}
    .breadcrumb {{ display: flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: rgba(56, 189, 248, 0.15); color: var(--accent); }}
    .api-controls {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      width: 100%;
    }}
    .status-badge {{
      padding: 6px 10px;
      border-radius: 10px;
      border: 1px solid var(--border);
      font-size: 12px;
    }}
    .status-badge.success {{ color: var(--accent-3); background: rgba(34, 197, 94, 0.12); border-color: rgba(34, 197, 94, 0.3); }}
    .status-badge.error {{ color: var(--error); background: rgba(248, 113, 113, 0.12); border-color: rgba(248, 113, 113, 0.35); }}
    .status-badge.info {{ color: var(--accent); background: rgba(56, 189, 248, 0.12); border-color: rgba(56, 189, 248, 0.35); }}
    @media (max-width: 768px) {{
      th, td {{ padding: 6px; font-size: 12px; }}
      .subgrid {{ grid-template-columns: 1fr; }}
      .api-controls {{ flex-direction: column; align-items: flex-start; }}
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
    <div class="api-controls">
      <input id="apiBaseInput" type="text" placeholder="API Base URL (예: https://api.example.com)" />
      <input id="apiTokenInput" type="password" placeholder="Bearer 토큰" />
      <button id="refreshApiBtn" type="button">유저/팀 새로고침</button>
      <span id="apiStatus" class="status-badge muted">준비</span>
    </div>
  </header>
  <div class="breadcrumb" id="breadcrumb">
    <span>경로:</span> <span id="crumb-org">-</span> <span>›</span> <span id="crumb-person">-</span> <span>›</span> <span id="crumb-deal">-</span>
  </div>
  <section class="card top-memo" id="orgMemoCard" style="width:100%;">
    <h2>회사 메모 (organizationId만 연결)</h2>
    <div class="muted" id="orgMemoHint">회사를 선택하세요.</div>
    <div style="overflow:auto;">
      <table id="orgMemoTable"></table>
    </div>
  </section>
  <section class="card stack" id="apiCard" style="width:100%;">
    <h2>유저/팀 (API)</h2>
    <div class="muted" id="apiHint">Base URL과 토큰을 입력하고 새로고침을 누르세요.</div>
    <div class="subgrid">
      <div>
        <h3>유저 목록</h3>
        <div class="muted" id="userHint">데이터가 없습니다.</div>
        <div class="table-wrap">
          <table id="userTable"></table>
        </div>
      </div>
      <div>
        <h3>팀 목록</h3>
        <div class="muted" id="teamHint">데이터가 없습니다.</div>
        <div class="table-wrap">
          <table id="teamTable"></table>
        </div>
      </div>
    </div>
  </section>
  <main class="grid">
    <section class="card stack">
      <h2>People (딜 있음)</h2>
      <div class="muted" id="peopleWithHint">회사를 선택하세요.</div>
      <div class="table-wrap">
        <table id="peopleWithTable"></table>
      </div>
      <div class="subgrid">
        <div>
          <h3>Deal</h3>
          <div class="muted" id="dealWithHint">사람을 선택하세요.</div>
          <div class="table-wrap">
            <table id="dealWithTable"></table>
          </div>
        </div>
        <div class="memos">
          <div class="memo-block">
            <h3>People 메모</h3>
            <div class="muted" id="personMemoWithHint">사람을 선택하세요.</div>
            <div class="table-wrap half">
              <table id="personMemoWithTable"></table>
            </div>
          </div>
          <div class="memo-block">
            <h3>Deal 메모</h3>
            <div class="muted" id="dealMemoWithHint">딜을 선택하세요.</div>
            <div class="table-wrap half">
              <table id="dealMemoWithTable"></table>
            </div>
          </div>
        </div>
      </div>
    </section>
    <section class="card stack">
      <h2>People (딜 없음)</h2>
      <div class="muted" id="peopleWithoutHint">회사를 선택하세요.</div>
      <div class="table-wrap">
        <table id="peopleWithoutTable"></table>
      </div>
      <div class="subgrid">
        <div>
          <h3>Deal</h3>
          <div class="muted" id="dealWithoutHint">사람을 선택하세요.</div>
          <div class="table-wrap">
            <table id="dealWithoutTable"></table>
          </div>
        </div>
        <div class="memos">
          <div class="memo-block">
            <h3>People 메모</h3>
            <div class="muted" id="personMemoWithoutHint">사람을 선택하세요.</div>
            <div class="table-wrap half">
              <table id="personMemoWithoutTable"></table>
            </div>
          </div>
          <div class="memo-block">
            <h3>Deal 메모</h3>
            <div class="muted" id="dealMemoWithoutHint">딜을 선택하세요.</div>
            <div class="table-wrap half">
              <table id="dealMemoWithoutTable"></table>
            </div>
          </div>
        </div>
      </div>
    </section>
  </main>
  <script id="data" type="application/json">{json.dumps(payload, ensure_ascii=False)}</script>
  <script>
    const DATA = JSON.parse(document.getElementById('data').textContent);
    const API_CONFIG = DATA.apiConfig || {{ baseUrl: '', token: '' }};
    let sizeFilter = '대기업';
    let stateWith = {{ orgId: "{default_org}", personId: null, dealId: null }};
    let stateWithout = {{ orgId: "{default_org}", personId: null, dealId: null }};
    const apiState = {{ users: [], teams: [], userById: {{}}, userTeams: {{}}, loading: false, error: '' }};

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

    function setApiStatus(msg, tone = 'muted') {{
      const el = document.getElementById('apiStatus');
      el.textContent = msg;
      el.className = `status-badge ${{tone}}`;
    }}

    function hydrateApiInputs() {{
      const baseInput = document.getElementById('apiBaseInput');
      const tokenInput = document.getElementById('apiTokenInput');
      baseInput.value = API_CONFIG.baseUrl || '';
      tokenInput.value = API_CONFIG.token || '';
    }}

    async function fetchJson(path, config) {{
      const base = (config.baseUrl || '').replace(/\\/+$/, '');
      if (!base) throw new Error('API base URL이 필요합니다.');
      if (!config.token) throw new Error('API 토큰이 필요합니다.');
      const headers = {{
        'Content-Type': 'application/json',
        Authorization: `Bearer ${{config.token}}`,
      }};
      const resp = await fetch(`${{base}}${{path}}`, {{ headers }});
      let data = null;
      try {{
        data = await resp.json();
      }} catch (e) {{
        // swallow parse errors
      }}
      if (!resp.ok) {{
        throw new Error((data && data.message) || `HTTP ${{resp.status}}`);
      }}
      if (data && data.success === false) {{
        throw new Error(data.message || 'API success=false');
      }}
      return data ? data.data : null;
    }}

    async function fetchWithBackoff(fn, retries = 2, baseDelay = 500) {{
      let lastErr;
      for (let attempt = 0; attempt <= retries; attempt++) {{
        try {{
          return await fn();
        }} catch (err) {{
          lastErr = err;
          if (attempt === retries) break;
          const delay = baseDelay * Math.pow(2, attempt);
          await new Promise(res => setTimeout(res, delay));
        }}
      }}
      throw lastErr || new Error('API 호출 실패');
    }}

    async function fetchUsers(config) {{
      const data = await fetchJson('/v2/user', config);
      return (data && data.userList) || [];
    }}

    async function fetchTeams(config) {{
      const data = await fetchJson('/v2/team', config);
      return (data && data.teamList) || [];
    }}

    function renderUserTable() {{
      const table = document.getElementById('userTable');
      const hint = document.getElementById('userHint');
      const users = apiState.users || [];
      if (!users.length) {{
        table.innerHTML = '';
        hint.textContent = apiState.loading ? '불러오는 중...' : '유저 데이터가 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>이름</th><th>상태</th><th>이메일</th><th>역할</th><th>업데이트</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      users.forEach(u => {{
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{u.name || '-'}}</td>
          <td>${{u.status || '-'}}</td>
          <td>${{u.email || '-'}}</td>
          <td>${{u.role || '-'}}</td>
          <td>${{formatDate(u.updatedAt)}}</td>
        `;
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    function renderTeamTable() {{
      const table = document.getElementById('teamTable');
      const hint = document.getElementById('teamHint');
      const teams = apiState.teams || [];
      if (!teams.length) {{
        table.innerHTML = '';
        hint.textContent = apiState.loading ? '불러오는 중...' : '팀 데이터가 없습니다.';
        return;
      }}
      hint.textContent = '';
      table.innerHTML = `<thead><tr><th>팀 이름</th><th>설명</th><th>구성원</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      teams.forEach(t => {{
        const names = (t.teammateList || []).map(tm => apiState.userById[tm.id]?.name || tm.name || tm.id).join(', ') || '-';
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{t.name || '-'}}</td>
          <td>${{t.description || '-'}} </td>
          <td>${{names}}</td>
        `;
        tbody.appendChild(tr);
      }});
      table.appendChild(tbody);
    }}

    async function refreshApiData() {{
      const baseInput = document.getElementById('apiBaseInput');
      const tokenInput = document.getElementById('apiTokenInput');
      const config = {{ baseUrl: baseInput.value.trim(), token: tokenInput.value.trim() }};
      if (!config.baseUrl || !config.token) {{
        setApiStatus('Base URL/토큰을 입력하세요.', 'error');
        return;
      }}
      apiState.loading = true;
      apiState.error = '';
      setApiStatus('유저/팀 불러오는 중...', 'info');
      try {{
        const [users, teams] = await Promise.all([
          fetchWithBackoff(() => fetchUsers(config)),
          fetchWithBackoff(() => fetchTeams(config)),
        ]);
        apiState.users = users;
        apiState.teams = teams;
        apiState.userById = Object.fromEntries(users.map(u => [u.id, u]));
        apiState.userTeams = {{}};
        teams.forEach(team => {{
          (team.teammateList || []).forEach(tm => {{
            const list = apiState.userTeams[tm.id] || (apiState.userTeams[tm.id] = []);
            list.push(team.name || team.id);
          }});
        }});
        renderUserTable();
        renderTeamTable();
        document.getElementById('apiHint').textContent = '';
        setApiStatus('동기화 완료', 'success');
      }} catch (err) {{
        apiState.error = err.message || String(err);
        setApiStatus(apiState.error, 'error');
      }} finally {{
        apiState.loading = false;
      }}
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

    document.getElementById('refreshApiBtn').addEventListener('click', refreshApiData);

    renderSizeSelect();
    renderOrgSelect();
    applyOrgSelection(stateWith.orgId);
    hydrateApiInputs();
    if ((API_CONFIG.baseUrl || '') && (API_CONFIG.token || '')) {{
      setApiStatus('사전 설정된 API로 불러오는 중...', 'info');
      refreshApiData();
    }} else {{
      setApiStatus('Base URL/토큰을 입력하세요.', 'muted');
    }}
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
    parser.add_argument("--api-base-url", default=None, help="Base URL for user/team API calls (ex: https://api.example.com)")
    parser.add_argument("--api-token", default=None, help="Bearer token for user/team API calls (optional, also reads API_TOKEN env).")
    args = parser.parse_args()

    db_path = Path(args.db_path or "salesmap_latest.db")
    if not db_path.exists():
        raise SystemExit(f"DB not found at {db_path}")

    raw = load_data(db_path, args.org_id, args.org_name, args.limit_orgs)
    maps = build_maps(raw)
    default_org = maps["organizations"][0]["id"]
    api_config = {
        "baseUrl": args.api_base_url or os.environ.get("API_BASE_URL", ""),
        "token": args.api_token or os.environ.get("API_TOKEN", ""),
    }
    render_html(maps, default_org, Path(args.output), api_config=api_config)


if __name__ == "__main__":
    main()

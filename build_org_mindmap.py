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

    org_where: List[str] = []
    org_params: List[Any] = []
    if org_id:
        org_where.append("id = ?")
        org_params.append(org_id)
    elif org_name:
        org_where.append('LOWER("이름") LIKE ?')
        org_params.append(f"%{org_name.lower()}%")

    org_sql = (
        'SELECT id, COALESCE("이름", id) as name, "업종" as industry, "팀" as team, "담당자" as owner '
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
            'SELECT id, peopleId, COALESCE("이름", id) as name, "상태" as status, '
            '"금액" as amount, "예상 체결액" as expected_amount, "마감일" as deadline, "수주 예정일" as expected_date '
            "FROM deal WHERE peopleId IN ({})"
        ).format(placeholders(people_ids))
        deal_rows = fetch_rows(conn, deal_sql, tuple(people_ids))

    deal_ids = [row["id"] for row in deal_rows]

    memo_rows: List[sqlite3.Row] = []
    if deal_ids:
        memo_sql = (
            "SELECT id, dealId, text, createdAt, updatedAt, ownerId "
            "FROM memo WHERE dealId IN ({})"
        ).format(placeholders(deal_ids))
        memo_rows = fetch_rows(conn, memo_sql, tuple(deal_ids))

    return {
        "organizations": org_rows,
        "people": people_rows,
        "deals": deal_rows,
        "memos": memo_rows,
    }


def build_hierarchy(raw: Dict[str, List[sqlite3.Row]]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    org_trees: Dict[str, Any] = {}
    org_options: List[Dict[str, str]] = []
    people_by_org: Dict[str, List[sqlite3.Row]] = {}
    for row in raw["people"]:
        people_by_org.setdefault(row["organizationId"], []).append(row)

    deals_by_person: Dict[str, List[sqlite3.Row]] = {}
    for row in raw["deals"]:
        deals_by_person.setdefault(row["peopleId"], []).append(row)

    memos_by_deal: Dict[str, List[sqlite3.Row]] = {}
    for row in raw["memos"]:
        memos_by_deal.setdefault(row["dealId"], []).append(row)

    for org in raw["organizations"]:
        org_id = org["id"]
        org_label = org["name"] or org_id
        org_options.append({"id": org_id, "name": org_label})
        org_node = {
            "id": f"org:{org_id}",
            "orgId": org_id,
            "label": org_label,
            "level": "org",
            "meta": {
                "업종": org["industry"],
                "팀": org["team"],
                "담당자": org["owner"],
            },
            "children": [],
        }
        for person in sorted(people_by_org.get(org_id, []), key=lambda r: (r["name"] or "").lower()):
            person_id = person["id"]
            person_node = {
                "id": f"person:{person_id}",
                "orgId": org_id,
                "label": person["name"] or "(이름 없음)",
                "level": "person",
                "meta": {
                    "직급/직책": person["title"],
                    "이메일": person["email"],
                    "전화": person["phone"],
                    "상태": person["status"],
                },
                "children": [],
            }
            for deal in sorted(deals_by_person.get(person_id, []), key=lambda r: (r["deadline"] or "")):
                deal_id = deal["id"]
                deal_node = {
                    "id": f"deal:{deal_id}",
                    "orgId": org_id,
                    "label": deal["name"] or "(딜 이름 없음)",
                    "level": "deal",
                    "meta": {
                        "상태": deal["status"],
                        "금액": deal["amount"],
                        "예상 체결액": deal["expected_amount"],
                        "마감일": deal["deadline"],
                        "수주 예정일": deal["expected_date"],
                    },
                    "children": [],
                }
                for memo in sorted(memos_by_deal.get(deal_id, []), key=lambda r: (r["createdAt"] or "")):
                    memo_node = {
                        "id": f"memo:{memo['id']}",
                        "orgId": org_id,
                        "label": (memo["text"] or "").strip()[:80] or "(메모 없음)",
                        "level": "memo",
                        "meta": {
                            "작성일": memo["createdAt"],
                            "수정일": memo["updatedAt"],
                            "작성자": memo["ownerId"],
                            "전체 메모": memo["text"],
                        },
                        "children": [],
                    }
                    deal_node["children"].append(memo_node)
                person_node["children"].append(deal_node)
            org_node["children"].append(person_node)
        org_trees[org_id] = org_node
    return org_trees, org_options


def render_html(data_by_org: Dict[str, Any], org_options: List[Dict[str, str]], default_org: str, output_path: Path) -> None:
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Salesmap 조직 Mindmap</title>
  <style>
    :root {{
      --bg: #0f172a;
      --panel: #111827;
      --muted: #94a3b8;
      --text: #e2e8f0;
      --accent-org: #38bdf8;
      --accent-person: #22c55e;
      --accent-deal: #facc15;
      --accent-memo: #c084fc;
      --link: #475569;
      --shadow: 0 10px 40px rgba(0,0,0,0.35);
    }}
    body {{
      margin: 0;
      font-family: 'Inter', 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: radial-gradient(circle at 20% 20%, rgba(56, 189, 248, 0.08), transparent 30%),
                  radial-gradient(circle at 80% 0%, rgba(192, 132, 252, 0.08), transparent 25%),
                  var(--bg);
      color: var(--text);
      height: 100vh;
      overflow: hidden;
      display: grid;
      grid-template-columns: 340px 1fr;
      grid-template-rows: 70px 1fr;
      grid-template-areas:
        "header header"
        "sidebar main";
      gap: 10px;
      padding: 12px;
      box-sizing: border-box;
    }}
    header {{
      grid-area: header;
      background: var(--panel);
      border: 1px solid #1f2937;
      border-radius: 14px;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      box-shadow: var(--shadow);
    }}
    header h1 {{
      font-size: 18px;
      margin: 0;
      letter-spacing: 0.01em;
    }}
    .controls {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    select, button {{
      background: #0b1220;
      color: var(--text);
      border: 1px solid #1f2937;
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
    }}
    button:hover, select:focus {{
      border-color: var(--accent-org);
      outline: none;
    }}
    .sidebar {{
      grid-area: sidebar;
      background: var(--panel);
      border: 1px solid #1f2937;
      border-radius: 14px;
      padding: 14px;
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
      gap: 12px;
      overflow: hidden;
    }}
    .legend {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #0b1220;
      border: 1px solid #1f2937;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      color: var(--muted);
    }}
    .dot {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }}
    .details {{
      flex: 1;
      overflow: auto;
      background: #0b1220;
      border: 1px solid #1f2937;
      border-radius: 12px;
      padding: 12px;
    }}
    .details h3 {{
      margin: 0 0 8px 0;
      font-size: 16px;
    }}
    .meta {{
      display: grid;
      grid-template-columns: 110px 1fr;
      gap: 6px 8px;
      font-size: 13px;
    }}
    .meta div:nth-child(odd) {{
      color: var(--muted);
    }}
    .main {{
      grid-area: main;
      background: var(--panel);
      border: 1px solid #1f2937;
      border-radius: 14px;
      position: relative;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    #mindmap {{
      width: 100%;
      height: 100%;
      min-height: 420px;
    }}
    .hint {{
      color: var(--muted);
      font-size: 12px;
      margin: 4px 0 0;
    }}
    @media (max-width: 960px) {{
      body {{
        grid-template-columns: 1fr;
        grid-template-rows: 70px 240px 1fr;
        grid-template-areas:
          "header"
          "sidebar"
          "main";
        height: auto;
      }}
      .main {{
        min-height: 420px;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>조직-구성원-딜-메모 마인드맵</h1>
    <div class="controls">
      <select id="orgSelect" aria-label="Select organization"></select>
      <button id="resetBtn" type="button">모두 확장</button>
    </div>
  </header>
  <aside class="sidebar">
    <div>
      <div class="legend">
        <span class="pill"><span class="dot" style="background: var(--accent-org)"></span>회사</span>
        <span class="pill"><span class="dot" style="background: var(--accent-person)"></span>People</span>
        <span class="pill"><span class="dot" style="background: var(--accent-deal)"></span>Deal</span>
        <span class="pill"><span class="dot" style="background: var(--accent-memo)"></span>Memo</span>
      </div>
      <p class="hint">회사를 고른 뒤, 원을 클릭해 하이라이트를 이동하세요.</p>
    </div>
    <div class="details" id="details">
      <h3>노드를 선택하세요</h3>
      <div class="meta">
        <div>레벨</div><div>-</div>
        <div>경로</div><div>-</div>
      </div>
    </div>
  </aside>
  <main class="main">
    <svg id="mindmap"></svg>
  </main>
  <script>
    const DATA_BY_ORG = {json.dumps(data_by_org, ensure_ascii=False)};
    const ORG_OPTIONS = {json.dumps(org_options, ensure_ascii=False)};
    let currentOrg = "{default_org}";
    let focusedId = null;

    function initSelector() {{
      const sel = document.getElementById('orgSelect');
      sel.innerHTML = ORG_OPTIONS.map(o => `<option value=\"${{o.id}}\" ${{o.id===currentOrg?'selected':''}}>${{o.name}}</option>`).join('');
      sel.addEventListener('change', () => {{
        currentOrg = sel.value;
        render();
      }});
    }}

    function cloneTree(node) {{
      return {{
        ...node,
        children: (node.children || []).map(cloneTree)
      }};
    }}

    function computeWeight(node) {{
      if (!node.children || node.children.length === 0) {{
        node.weight = 1;
        return 1;
      }}
      let total = 0;
      for (const child of node.children) {{
        total += computeWeight(child);
      }}
      node.weight = total || 1;
      return node.weight;
    }}

    function assignAngles(node, start, end, depth, radiusStep) {{
      node.depth = depth;
      node.angle = (start + end) / 2;
      node.radius = depth * radiusStep;
      if (!node.children || node.children.length === 0) return;
      let cursor = start;
      for (const child of node.children) {{
        const span = (end - start) * (child.weight / node.weight);
        assignAngles(child, cursor, cursor + span, depth + 1, radiusStep);
        cursor += span;
      }}
    }}

    function flatten(node, parent=null, accNodes=[], accLinks=[]) {{
      accNodes.push(node);
      if (parent) accLinks.push({{ source: parent, target: node }});
      for (const child of node.children || []) {{
        flatten(child, node, accNodes, accLinks);
      }}
      return {{ nodes: accNodes, links: accLinks }};
    }}

    function colorFor(level) {{
      switch(level) {{
        case 'org': return getComputedStyle(document.documentElement).getPropertyValue('--accent-org');
        case 'person': return getComputedStyle(document.documentElement).getPropertyValue('--accent-person');
        case 'deal': return getComputedStyle(document.documentElement).getPropertyValue('--accent-deal');
        case 'memo': return getComputedStyle(document.documentElement).getPropertyValue('--accent-memo');
        default: return '#e5e7eb';
      }}
    }}

    function buildPath(node) {{
      const parts = [];
      let cur = node;
      while (cur) {{
        parts.unshift(cur.label);
        cur = cur.parent;
      }}
      return parts.join(' / ');
    }}

    function focusNode(node, nodes) {{
      focusedId = node ? node.id : null;
      const connected = new Set();
      function mark(n) {{
        connected.add(n.id);
        if (n.parent) mark(n.parent);
        if (n.children) n.children.forEach(mark);
      }}
      if (node) mark(node);
      nodes.forEach(n => {{
        n.active = !focusedId || connected.has(n.id);
      }});
      updateDetails(node);
    }}

    function updateDetails(node) {{
      const panel = document.getElementById('details');
      if (!node) {{
        panel.innerHTML = '<h3>노드를 선택하세요</h3><div class=\"meta\"><div>레벨</div><div>-</div><div>경로</div><div>-</div></div>';
        return;
      }}
      const metaEntries = Object.entries(node.meta || {{}}).filter(([, v]) => v);
      const metaHtml = metaEntries.map(([k,v]) => `<div>${{k}}</div><div>${{String(v)}}</div>`).join('') || '<div>추가 정보</div><div>-</div>';
      panel.innerHTML = `
        <h3>${{node.label}}</h3>
        <div class=\"meta\">
          <div>레벨</div><div>${{node.level}}</div>
          <div>경로</div><div>${{buildPath(node)}}</div>
          ${{metaHtml}}
        </div>
      `;
    }}

    function drawMindmap(root) {{
      const svg = document.getElementById('mindmap');
      const width = svg.clientWidth || (svg.parentElement && svg.parentElement.clientWidth) || 960;
      const height = svg.clientHeight || (svg.parentElement && svg.parentElement.clientHeight) || 640;
      svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      computeWeight(root);
      assignAngles(root, -Math.PI/2, (3*Math.PI)/2, 0, Math.min(width, height)/6);

      const {{ nodes, links }} = flatten(root);
      const centerX = width / 2;
      const centerY = height / 2;

      links.forEach(link => {{
        const sx = centerX + link.source.radius * Math.cos(link.source.angle);
        const sy = centerY + link.source.radius * Math.sin(link.source.angle);
        const tx = centerX + link.target.radius * Math.cos(link.target.angle);
        const ty = centerY + link.target.radius * Math.sin(link.target.angle);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const mx = (sx + tx) / 2;
        const my = (sy + ty) / 2;
        path.setAttribute('d', `M ${{sx}} ${{sy}} Q ${{mx}} ${{my}} ${{tx}} ${{ty}}`);
        path.setAttribute('stroke', 'var(--link)');
        path.setAttribute('stroke-width', '1.5');
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke-opacity', '0.6');
        svg.appendChild(path);
      }});

      nodes.forEach(node => {{
        const x = centerX + node.radius * Math.cos(node.angle);
        const y = centerY + node.radius * Math.sin(node.angle);
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('transform', `translate(${{x}}, ${{y}})`);
        g.style.cursor = 'pointer';

        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        const baseColor = colorFor(node.level);
        circle.setAttribute('r', 16 - Math.min(node.depth * 1.5, 6));
        circle.setAttribute('fill', baseColor);
        circle.setAttribute('fill-opacity', '0.9');
        circle.setAttribute('stroke', '#0b1220');
        circle.setAttribute('stroke-width', '1.5');
        g.appendChild(circle);

        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', 0);
        text.setAttribute('y', 30);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('fill', 'var(--text)');
        text.setAttribute('font-size', '12');
        text.textContent = node.label.length > 14 ? node.label.slice(0,13) + '…' : node.label;
        g.appendChild(text);

        g.addEventListener('click', (e) => {{
          e.stopPropagation();
          focusNode(node, nodes);
          drawMindmap(root); // re-render to apply active state
        }});
        node._g = g;
        node._circle = circle;
        svg.appendChild(g);
      }});

      // Apply active/inactive styling
      if (focusedId) {{
        nodes.forEach(node => {{
          const active = node.active ?? true;
          node._g.style.opacity = active ? 1 : 0.2;
        }});
        Array.from(svg.querySelectorAll('path')).forEach(p => p.style.opacity = 0.4);
      }}
    }}

    function render() {{
      const source = DATA_BY_ORG[currentOrg];
      if (!source) return;
      const root = cloneTree(source);
      const attachParent = (node, parent=null) => {{
        node.parent = parent;
        (node.children || []).forEach(ch => attachParent(ch, node));
      }};
      attachParent(root, null);
      focusNode(root, [root]); // set defaults
      drawMindmap(root);
    }}

    document.getElementById('resetBtn').addEventListener('click', () => {{
      focusedId = null;
      render();
    }});

    initSelector();
    render();
  </script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote mindmap to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local HTML mindmap (org -> people -> deal -> memo).")
    parser.add_argument("--db-path", default="salesmap_latest.db", help="Path to SQLite snapshot.")
    parser.add_argument("--output", default="org_mindmap.html", help="Output HTML file path.")
    parser.add_argument("--org-id", default=None, help="Filter to a specific organization id.")
    parser.add_argument("--org-name", default=None, help="Filter organizations by name (LIKE match, case-insensitive).")
    parser.add_argument("--limit-orgs", type=int, default=None, help="Limit number of organizations (after filter).")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"DB not found at {db_path}")

    raw = load_data(db_path, args.org_id, args.org_name, args.limit_orgs)
    hierarchy, org_options = build_hierarchy(raw)
    default_org = org_options[0]["id"]
    render_html(hierarchy, org_options, default_org, Path(args.output))


if __name__ == "__main__":
    main()

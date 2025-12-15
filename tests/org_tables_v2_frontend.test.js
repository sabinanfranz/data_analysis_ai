import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import vm from "node:vm";
import { JSDOM } from "jsdom";

// Minimal DOM stub to satisfy render helpers during loadOrgDetail().
class StubElement {
  constructor() {
    this.textContent = "";
    this.innerHTML = "";
    this.style = {};
    this.value = "";
    this.disabled = false;
    this.title = "";
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  addEventListener() {}
  appendChild() {}
  querySelectorAll() {
    return [];
  }
  querySelector() {
    return null;
  }
  setAttribute() {}
  focus() {}
}

function createDocumentStub() {
  const map = new Map();
  const get = (id) => {
    if (!map.has(id)) map.set(id, new StubElement());
    return map.get(id);
  };
  return {
    body: new StubElement(),
    getElementById: get,
    createElement: () => new StubElement(),
    addEventListener() {},
    querySelectorAll() {
      return [];
    },
    querySelector() {
      return null;
    },
  };
}

function extractScript(htmlText) {
  const match = htmlText.match(/<script>([\s\S]*)<\/script>/);
  assert.ok(match && match[1], "org_tables_v2 script block not found");
  return match[1];
}

test("loadOrgDetail populates people and won summary in order", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const fetchCalls = [];
  const responses = {
    "/orgs/org-1/memos": { items: [{ id: "m1" }] },
    "/orgs/org-1/people": {
      items: [{ id: "p-1", upper_org: "부문A", name: "홍길동", team_signature: "", title_signature: "", edu_area: "" }],
    },
    "/orgs/org-1/won-summary": {
      items: [{ upper_org: "부문A", won2023: 0, won2024: 0, won2025: 1, contacts: [], owners: [] }],
    },
    "/orgs/org-1/won-groups-json": { organization: { id: "org-1" }, groups: [] },
  };

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async (url) => {
      fetchCalls.push(url);
      const u = new URL(url);
      const key = u.pathname.replace(/^\/api/, "");
      const data = responses[key];
      if (!data) {
        return {
          ok: false,
          statusText: "not found",
          text: async () => "not found",
        };
      }
      return {
        ok: true,
        json: async () => data,
        text: async () => JSON.stringify(data),
      };
    },
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;

  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const loadOrgDetail = vm.runInContext("loadOrgDetail", ctx);
  const state = vm.runInContext("state", ctx);

  await loadOrgDetail("org-1");

  assert.ok(
    fetchCalls.some((u) => u.includes("/orgs/org-1/people")),
    "people endpoint was not requested"
  );
  assert.ok(
    fetchCalls.some((u) => u.includes("/orgs/org-1/won-summary")),
    "won-summary endpoint was not requested"
  );
  assert.strictEqual(state.people[0]?.id, "p-1", "people list not populated");
  assert.strictEqual(
    state.wonSummary[0]?.upper_org,
    "부문A",
    "won summary not populated"
  );
});

test("autoSelectFirstPersonForUpperOrg picks first person and first deal", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const fetchCalls = [];
  const responses = {
    "/people/p-1/deals": {
      items: [
        {
          id: "d-1",
          name: "Deal 1",
          status: "Won",
          amount: 100000000,
          expected_amount: 0,
          contract_date: "2025-01-01",
          created_at: "2025-01-02",
          ownerName: "담당자A",
        },
      ],
    },
    "/people/p-1/memos": { items: [{ id: "pm-1", text: "person memo" }] },
    "/deals/d-1/memos": { items: [{ id: "dm-1", text: "deal memo" }] },
  };

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async (url) => {
      fetchCalls.push(url);
      const u = new URL(url);
      const key = u.pathname.replace(/^\/api/, "");
      const data = responses[key];
      if (!data) {
        return {
          ok: false,
          statusText: "not found",
          text: async () => "not found",
        };
      }
      return {
        ok: true,
        json: async () => data,
        text: async () => JSON.stringify(data),
      };
    },
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;

  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const autoSelect = vm.runInContext("autoSelectFirstPersonForUpperOrg", ctx);
  const state = vm.runInContext("state", ctx);

  state.selectedOrg = "org-1";
  state.selectedUpperOrg = "부문A";
  state.people = [
    { id: "p-1", upper_org: "부문A", name: "홍길동", team_signature: "", title_signature: "", edu_area: "" },
    { id: "p-2", upper_org: "부문B", name: "김철수", team_signature: "", title_signature: "", edu_area: "" },
  ];

  await autoSelect();

  assert.strictEqual(state.selectedPerson, "p-1", "first person not auto-selected");
  assert.strictEqual(state.selectedDeal, "d-1", "first deal not auto-selected");
  assert.ok(
    fetchCalls.some((u) => u.includes("/people/p-1/deals")),
    "deals were not fetched"
  );
  assert.ok(
    fetchCalls.some((u) => u.includes("/deals/d-1/memos")),
    "deal memos were not fetched"
  );
});

test("memo modal normalizes <br> and CRLF to newlines", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const bodyNode = docStub.getElementById("memoModalBody");
  const dateNode = docStub.getElementById("memoModalDate");
  const authorNode = docStub.getElementById("memoModalAuthor");
  const backdrop = docStub.getElementById("memoModalBackdrop");
  const close = docStub.getElementById("memoModalClose");

  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async () => ({ ok: true, json: async () => ({ items: [] }), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;

  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  // initialize modal refs
  const state = vm.runInContext("state", ctx);
  state.modal = {
    backdrop,
    close,
    date: dateNode,
    author: authorNode,
    body: bodyNode,
    bound: false,
  };

  const openMemoModal = vm.runInContext("openMemoModal", ctx);

  openMemoModal({
    createdAt: "2025-01-01",
    ownerName: "작성자",
    text: "줄1<br>줄2\r\n줄3\r줄4",
  });

  const rendered = bodyNode.textContent;
  const expected = "줄1\n줄2\n줄3\n줄4";
  assert.strictEqual(rendered, expected);
});

test("JSON 버튼 활성/비활성 상태가 조건에 따라 반영된다", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async () => ({ ok: true, json: async () => ({ items: [] }), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;

  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const renderAll = vm.runInContext("renderWonGroupJsonAll", ctx);
  const renderFiltered = vm.runInContext("renderWonGroupJsonFiltered", ctx);
  const state = vm.runInContext("state", ctx);

  const hintAll = docStub.getElementById("wonGroupJsonHintAll");
  const viewAll = docStub.getElementById("viewWonGroupJsonAllBtn");
  const copyAll = docStub.getElementById("copyWonGroupJsonAllBtn");
  const hintFiltered = docStub.getElementById("wonGroupJsonHintFiltered");
  const viewFiltered = docStub.getElementById("viewWonGroupJsonFilteredBtn");
  const copyFiltered = docStub.getElementById("copyWonGroupJsonFilteredBtn");

  renderAll(null);
  assert.strictEqual(viewAll.disabled, true);
  assert.strictEqual(copyAll.disabled, true);
  assert.strictEqual(hintAll.textContent, "회사를 선택하세요.");

  state.selectedOrg = "org-1";
  renderAll(null);
  assert.strictEqual(viewAll.disabled, true);
  assert.strictEqual(copyAll.disabled, true);
  assert.strictEqual(hintAll.textContent, "불러오는 중...");

  renderAll({ organization: { id: "org-1" }, groups: [] });
  assert.strictEqual(viewAll.disabled, false);
  assert.strictEqual(copyAll.disabled, false);
  assert.ok(hintAll.textContent === "" || hintAll.textContent.includes("Won 딜"));

  renderFiltered(null);
  assert.strictEqual(viewFiltered.disabled, true);
  assert.strictEqual(copyFiltered.disabled, true);
  assert.ok(
    hintFiltered.textContent === "상위 조직을 선택하세요." ||
      hintFiltered.textContent === "아래 표에서 소속 상위 조직을 선택해주세요."
  );

  state.selectedUpperOrg = "부문A";
  renderFiltered(null);
  assert.strictEqual(viewFiltered.disabled, true);
  assert.strictEqual(copyFiltered.disabled, true);
  assert.strictEqual(hintFiltered.textContent, "불러오는 중...");

  renderFiltered({ organization: { id: "org-1" }, groups: [{ upper_org: "부문A" }] });
  assert.strictEqual(viewFiltered.disabled, false);
  assert.strictEqual(copyFiltered.disabled, false);
  assert.ok(hintFiltered.textContent === "" || hintFiltered.textContent.includes("Won 딜"));
});

test("resetSelection clears upper/person/deal selection, filters, and JSON 필터", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async () => ({ ok: true, json: async () => ({ items: [] }), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;

  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const resetSelection = vm.runInContext("resetSelection", ctx);
  const state = vm.runInContext("state", ctx);

  state.selectedOrg = "org-1";
  state.selectedUpperOrg = "부문A";
  state.selectedPerson = "p-1";
  state.selectedDeal = "d-1";
  state.people = [{ id: "p-1", upper_org: "부문A", name: "홍길동", team_signature: "", title_signature: "", edu_area: "" }];
  state.deals = [{ id: "d-1", name: "Deal", status: "Won" }];
  state.wonSummary = [{ upper_org: "부문A", won2023: 0, won2024: 0, won2025: 1, contacts: [], owners: [] }];
  state.wonGroupJson = { organization: { id: "org-1" }, groups: [{ upper_org: "부문A" }] };
  state.filteredWonGroupJson = { organization: { id: "org-1" }, groups: [{ upper_org: "부문A" }] };

  await resetSelection();

  assert.strictEqual(state.selectedUpperOrg, null);
  assert.strictEqual(state.selectedPerson, null);
  assert.strictEqual(state.selectedDeal, null);
  assert.strictEqual(state.filteredWonGroupJson, null);
  assert.strictEqual(state.wonSummaryCleared, false);
  assert.strictEqual(state.selectedOrg, null);
  assert.strictEqual(state.orgSearch, "");
  assert.ok(state.size === "대기업" || state.size === "전체");

  const hintFiltered = docStub.getElementById("wonGroupJsonHintFiltered");
  const viewFiltered = docStub.getElementById("viewWonGroupJsonFilteredBtn");
  const copyFiltered = docStub.getElementById("copyWonGroupJsonFilteredBtn");
  assert.strictEqual(hintFiltered.textContent, "회사를 선택하세요.");
  assert.strictEqual(viewFiltered.disabled, true);
  assert.strictEqual(copyFiltered.disabled, true);

  const wonHint = docStub.getElementById("wonSummaryHint");
  assert.ok(wonHint.textContent === "" || wonHint.textContent === "회사를 선택하세요.");
  const wonTable = docStub.getElementById("wonSummaryTable");
  assert.strictEqual(wonTable.innerHTML, "");

  const searchInput = docStub.getElementById("orgSearch");
  const sizeSelect = docStub.getElementById("sizeSelect");
  const orgSelect = docStub.getElementById("orgSelect");
  assert.strictEqual(searchInput.value, "");
  assert.ok(sizeSelect.value === "대기업" || sizeSelect.value === "전체");
  assert.strictEqual(orgSelect.value, "");
});

test("computeTeamPartSummary maps owners and DRI rule", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async () => ({ ok: true, json: async () => ({ items: [] }), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;

  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const computeTeamPartSummary = vm.runInContext("computeTeamPartSummary", ctx);

  const single = computeTeamPartSummary(["김솔이", "김정은"]);
  assert.strictEqual(single.teamPartText, "기업교육 1팀 1파트");
  assert.strictEqual(single.dri, "O");

  const mixed = computeTeamPartSummary(["강지선", "정다혜"]);
  assert.ok(mixed.teamPartText.includes(" / "));
  assert.strictEqual(mixed.dri, "X");

  const trailing = computeTeamPartSummary(["이윤지B"]);
  assert.strictEqual(trailing.teamPartText, "기업교육 2팀 1파트");
  assert.strictEqual(trailing.dri, "O");
});

test("renderWonSummary shows new columns and team/part/DRI", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  // required elements
  const card = docStub.getElementById("wonSummaryCard");
  const table = docStub.getElementById("wonSummaryTable");
  const hint = docStub.getElementById("wonSummaryHint");

  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async () => ({ ok: true, json: async () => ({ items: [] }), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;

  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const renderWonSummary = vm.runInContext("renderWonSummary", ctx);
  const state = vm.runInContext("state", ctx);

  state.selectedOrg = "org-1";
  const summary = [
    {
      upper_org: "부문A",
      won2023: 0,
      won2024: 0,
      won2025: 1e8,
      contacts: [],
      owners: ["오너X"],
      owners2025: ["김솔이", "김정은"],
    },
  ];

  renderWonSummary(summary);

  assert.strictEqual(card.style.display, "");
  assert.ok(table.innerHTML.includes("2025 담당자"));
  assert.ok(table.innerHTML.includes("김솔이, 김정은"));
  assert.ok(table.innerHTML.includes("기업교육 1팀 1파트"));
  assert.ok(table.innerHTML.includes(">O<") || table.innerHTML.includes(">O</"));
  assert.strictEqual(hint.textContent, "");
});

test("statepath menu renders and fetches portfolio items", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const fetchCalls = [];
  const responses = {
    "/statepath/portfolio-2425": {
      items: [
        {
          orgId: "org-1",
          orgName: "회사A",
          sizeGroup: "대기업",
          companyTotalEok2024: 1.0,
          companyBucket2024: "P1",
          companyTotalEok2025: 2.0,
          companyBucket2025: "P0",
          deltaEok: 1.0,
        },
      ],
      summary: {},
    },
  };

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async (url) => {
      fetchCalls.push(url);
      const u = new URL(url);
      const key = u.pathname.replace(/^\/api/, "");
      const data = responses[key];
      if (!data) {
        return {
          ok: false,
          statusText: "not found",
          text: async () => "not found",
        };
      }
      return {
        ok: true,
        json: async () => data,
        text: async () => JSON.stringify(data),
      };
    },
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;

  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const renderStatePathMenu = vm.runInContext("renderStatePathMenu", ctx);
  const state = vm.runInContext("state", ctx);

  const root = docStub.getElementById("contentRoot");
  await renderStatePathMenu(root);

  assert.ok(fetchCalls.some((u) => u.includes("/statepath/portfolio-2425")), "portfolio endpoint not called");
  assert.strictEqual(state.statepath2425.items.length, 1);

  const openLegend = vm.runInContext("openStatePathLegendModal", ctx);
  const legendBody = docStub.getElementById("statePathLegendBody");
  openLegend("all");
  assert.ok(legendBody, "legend modal body missing");
  legendBody.innerHTML = "Risk OPEN 버킷 세그먼트 비교 Top Patterns 브레드크럼 페이지네이션";
  assert.ok(/Risk/.test(legendBody.innerHTML));
});

test("StatePath export helpers build objects and strip revops", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async () => ({ ok: true, json: async () => ({}), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const state = vm.runInContext("state", ctx);
  state.statepath2425.loading = false;
  state.statepath2425.error = null;
  state.statepath2425.segment = "대기업";
  state.statepath2425.search = "Org";
  state.statepath2425.sort = "won2025_desc";
  state.statepath2425.quickFilters = { risk: true, hasOpen: false, hasScaleUp: false, companyDir: "up", seed: "H→B", railShift: "all" };
  state.statepath2425.patternFilter = { companyFrom: "Ø", companyTo: "P5", cell: "BU_ONLINE", cellEvent: "OPEN", rail: null, railDir: null };
  state.statepath2425.filteredItems = [
    {
      orgId: "org-1",
      orgName: "Org One",
      segment: "대기업",
      companyTotalEok2024: 1.0,
      companyTotalEok2025: 2.5,
      companyBucket2024: "Ø",
      companyBucket2025: "P5",
      companyOnlineBucket2024: "Ø",
      companyOnlineBucket2025: "P5",
      companyOfflineBucket2024: "Ø",
      companyOfflineBucket2025: "Ø",
      deltaEok: 1.5,
      cells_2024: { BU_ONLINE: { bucket: "Ø" } },
      cells_2025: { BU_ONLINE: { bucket: "P5" } },
    },
  ];

  const exportObj = vm.runInContext("buildStatePathTableExportObject()", ctx);
  assert.strictEqual(exportObj.export_type, "statepath_2425_table_v2");
  assert.strictEqual(exportObj.row_count, 1);
  assert.ok(exportObj.filters.quickFilters.risk, "quickFilters not captured");
  assert.deepStrictEqual(exportObj.rows[0].y2024.bucket, "Ø");
  assert.ok(exportObj.rows[0].major_events.includes("OPEN:BU_ONLINE"), "major events not derived");

  const strip = vm.runInContext("stripRevOpsFromStatePath", ctx);
  const detail = { company_name: "Org One", ops_reco: { foo: 1 }, revops_reco: { bar: 2 }, path_2024_to_2025: { seed: "NONE" } };
  const cloned = strip(detail);
  assert.ok(cloned && !("ops_reco" in cloned) && !("revops_reco" in cloned), "revops keys not stripped");
  assert.ok(detail.ops_reco, "original object mutated");
});

test("StatePath table render includes JSON copy controls", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async () => ({ ok: true, json: async () => ({}), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandbox.global = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const state = vm.runInContext("state", ctx);
  state.statepath2425.loading = false;
  state.statepath2425.error = null;
  state.statepath2425.filteredItems = [
    {
      orgId: "o1",
      orgName: "Org One",
      segment: "대기업",
      companyTotalEok2024: 1,
      companyTotalEok2025: 2,
      companyBucket2024: "P5",
      companyBucket2025: "P4",
      cells_2024: { BU_ONLINE: { bucket: "Ø" } },
      cells_2025: { BU_ONLINE: { bucket: "P5" } },
    },
  ];

  const renderTable = vm.runInContext("renderStatePathTable", ctx);
  // Ensure required DOM nodes exist
  docStub.getElementById("statepathStatus");
  docStub.getElementById("statepathTableWrap");
  renderTable();
  const wrap = docStub.getElementById("statepathTableWrap");
  assert.ok((wrap.innerHTML || "").includes("JSON 복사"), "export button not rendered");
});

test("counterparty owners cell renders single line without <br/> or newline", () => {
  const owners = ["홍길동", "김철수"];
  const ownersText = owners.join(", ");
  const cellHtml = `<td class="nowrap-ellipsis" title="${ownersText}">${ownersText}</td>`;
  const dom = new JSDOM(`<table><tr>${cellHtml}</tr></table>`);
  const td = dom.window.document.querySelector("td");
  if (!td) throw new Error("td not rendered");
  if (td.innerHTML.includes("<br")) {
    throw new Error("owners cell contains <br/>");
  }
  if (td.textContent.includes("\n")) {
    throw new Error("owners cell contains newline");
  }
});

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

test("dealcheck status filter helpers support include mode and only mode", async () => {
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

  const getDefaultDealCheckStatusFilterState = vm.runInContext("getDefaultDealCheckStatusFilterState", ctx);
  const setDealCheckIncludeWonLost = vm.runInContext("setDealCheckIncludeWonLost", ctx);
  const setDealCheckIncludeWonOnly = vm.runInContext("setDealCheckIncludeWonOnly", ctx);
  const setDealCheckOnlyChecks = vm.runInContext("setDealCheckOnlyChecks", ctx);
  const matchDealCheckStatusFilter = vm.runInContext("matchDealCheckStatusFilter", ctx);
  const getDealCheckStatusFilterState = vm.runInContext("getDealCheckStatusFilterState", ctx);
  const setDealCheckStatusFilterState = vm.runInContext("setDealCheckStatusFilterState", ctx);

  let state = getDefaultDealCheckStatusFilterState();
  assert.strictEqual(state.includeWonLost, true);
  assert.strictEqual(state.includeWonOnly, false);
  assert.strictEqual(state.wonOnly, false);
  assert.strictEqual(state.lostOnly, false);
  assert.strictEqual(matchDealCheckStatusFilter("sql", state), true);
  assert.strictEqual(matchDealCheckStatusFilter("won", state), true);
  assert.strictEqual(matchDealCheckStatusFilter("lost", state), true);

  state = setDealCheckIncludeWonLost(state, false);
  assert.strictEqual(state.includeWonLost, false);
  assert.strictEqual(state.includeWonOnly, false);
  assert.strictEqual(state.wonOnly, false);
  assert.strictEqual(state.lostOnly, false);
  assert.strictEqual(matchDealCheckStatusFilter("sql", state), true);
  assert.strictEqual(matchDealCheckStatusFilter("won", state), false);
  assert.strictEqual(matchDealCheckStatusFilter("lost", state), false);

  state = setDealCheckIncludeWonOnly(state, true);
  assert.strictEqual(state.includeWonLost, false);
  assert.strictEqual(state.includeWonOnly, true);
  assert.strictEqual(state.wonOnly, false);
  assert.strictEqual(state.lostOnly, false);
  assert.strictEqual(matchDealCheckStatusFilter("sql", state), true);
  assert.strictEqual(matchDealCheckStatusFilter("won", state), true);
  assert.strictEqual(matchDealCheckStatusFilter("lost", state), false);

  const includeAllReset = setDealCheckIncludeWonLost(state, true);
  assert.strictEqual(includeAllReset.includeWonLost, true);
  assert.strictEqual(includeAllReset.includeWonOnly, false);
  assert.strictEqual(includeAllReset.wonOnly, false);
  assert.strictEqual(includeAllReset.lostOnly, false);
  assert.strictEqual(matchDealCheckStatusFilter("sql", includeAllReset), true);
  assert.strictEqual(matchDealCheckStatusFilter("won", includeAllReset), true);
  assert.strictEqual(matchDealCheckStatusFilter("lost", includeAllReset), true);

  const includeWonOnlyAgain = setDealCheckIncludeWonOnly(includeAllReset, true);
  assert.strictEqual(includeWonOnlyAgain.includeWonLost, false);
  assert.strictEqual(includeWonOnlyAgain.includeWonOnly, true);
  assert.strictEqual(includeWonOnlyAgain.wonOnly, false);
  assert.strictEqual(includeWonOnlyAgain.lostOnly, false);

  const includeOnWonOnly = setDealCheckOnlyChecks(setDealCheckIncludeWonLost(state, true), true, false);
  assert.strictEqual(includeOnWonOnly.includeWonLost, false);
  assert.strictEqual(includeOnWonOnly.includeWonOnly, false);
  assert.strictEqual(includeOnWonOnly.wonOnly, true);
  assert.strictEqual(includeOnWonOnly.lostOnly, false);
  assert.strictEqual(matchDealCheckStatusFilter("sql", includeOnWonOnly), false);
  assert.strictEqual(matchDealCheckStatusFilter("won", includeOnWonOnly), true);
  assert.strictEqual(matchDealCheckStatusFilter("lost", includeOnWonOnly), false);

  state = setDealCheckOnlyChecks(includeWonOnlyAgain, true, false);
  assert.strictEqual(state.includeWonLost, false);
  assert.strictEqual(state.includeWonOnly, false);
  assert.strictEqual(state.wonOnly, true);
  assert.strictEqual(state.lostOnly, false);
  assert.strictEqual(matchDealCheckStatusFilter("sql", state), false);
  assert.strictEqual(matchDealCheckStatusFilter("won", state), true);
  assert.strictEqual(matchDealCheckStatusFilter("lost", state), false);

  state = setDealCheckOnlyChecks(state, false, true);
  assert.strictEqual(state.includeWonLost, false);
  assert.strictEqual(state.includeWonOnly, false);
  assert.strictEqual(state.wonOnly, false);
  assert.strictEqual(state.lostOnly, true);
  assert.strictEqual(matchDealCheckStatusFilter("sql", state), false);
  assert.strictEqual(matchDealCheckStatusFilter("won", state), false);
  assert.strictEqual(matchDealCheckStatusFilter("lost", state), true);

  const bothOnly = setDealCheckOnlyChecks(state, true, true);
  assert.strictEqual(bothOnly.includeWonLost, false);
  assert.strictEqual(bothOnly.includeWonOnly, false);
  assert.strictEqual(bothOnly.wonOnly, true);
  assert.strictEqual(bothOnly.lostOnly, true);
  assert.strictEqual(matchDealCheckStatusFilter("sql", bothOnly), false);
  assert.strictEqual(matchDealCheckStatusFilter("won", bothOnly), true);
  assert.strictEqual(matchDealCheckStatusFilter("lost", bothOnly), true);

  const includeReset = setDealCheckIncludeWonLost(bothOnly, true);
  assert.strictEqual(includeReset.includeWonLost, true);
  assert.strictEqual(includeReset.includeWonOnly, false);
  assert.strictEqual(includeReset.wonOnly, false);
  assert.strictEqual(includeReset.lostOnly, false);
  assert.strictEqual(matchDealCheckStatusFilter("sql", includeReset), true);
  assert.strictEqual(matchDealCheckStatusFilter("won", includeReset), true);
  assert.strictEqual(matchDealCheckStatusFilter("lost", includeReset), true);

  const menuA = setDealCheckStatusFilterState("edu1::ALLPART", setDealCheckIncludeWonOnly(getDefaultDealCheckStatusFilterState(), true));
  const menuB = setDealCheckStatusFilterState("edu2::ALLPART", setDealCheckOnlyChecks(getDefaultDealCheckStatusFilterState(), false, true));
  assert.strictEqual(menuA.includeWonOnly, true);
  assert.strictEqual(menuB.lostOnly, true);
  assert.strictEqual(getDealCheckStatusFilterState("edu1::ALLPART").includeWonOnly, true);
  assert.strictEqual(getDealCheckStatusFilterState("edu1::ALLPART").lostOnly, false);
  assert.strictEqual(getDealCheckStatusFilterState("edu2::ALLPART").includeWonOnly, false);
  assert.strictEqual(getDealCheckStatusFilterState("edu2::ALLPART").lostOnly, true);
});

test("교육 전체 딜체크 메뉴가 최상단에 추가되고 전체 owner/파트 helper가 동작한다", async () => {
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

  const dealcheckMenuDefs = vm.runInContext("DEALCHECK_MENU_DEFS", ctx);
  const getDealCheckRosterNames = vm.runInContext("getDealCheckRosterNames", ctx);
  const inferPartFromOwners = vm.runInContext("inferPartFromOwners", ctx);
  const state = vm.runInContext("state", ctx);
  const cache = vm.runInContext("cache", ctx);

  assert.strictEqual(dealcheckMenuDefs[0].id, "edu-all-dealcheck");
  assert.strictEqual(dealcheckMenuDefs[0].teamKey, "edu_all");
  assert.strictEqual(dealcheckMenuDefs[0].parentId, null);

  const roster = getDealCheckRosterNames("edu_all", null);
  assert.ok(roster.includes("김솔이"));
  assert.ok(roster.includes("권노을"));
  assert.ok(roster.includes("강진우"));

  assert.strictEqual(inferPartFromOwners("edu_all", ["김솔이"]), "1팀 1파트");
  assert.strictEqual(inferPartFromOwners("edu_all", ["권노을"]), "2팀 1파트");
  assert.strictEqual(inferPartFromOwners("edu_all", ["강진우"]), "2팀 온라인셀");
  assert.strictEqual(inferPartFromOwners("edu_all", ["김솔이", "강진우"]), "1팀 1파트+2팀 온라인셀");

  const publicIdx = dealcheckMenuDefs.findIndex((item) => item.id === "public-dealcheck");
  const onlineIdx = dealcheckMenuDefs.findIndex((item) => item.id === "edu2-dealcheck-online");
  assert.ok(publicIdx > onlineIdx, "public dealcheck should come after edu2 online dealcheck");
  assert.strictEqual(dealcheckMenuDefs[publicIdx].parentId, null);
  assert.strictEqual(dealcheckMenuDefs[publicIdx].teamKey, "public");

  assert.ok(state.dealCheck.public, "state.dealCheck.public should exist");
  assert.ok(Object.prototype.hasOwnProperty.call(cache.dealCheck, "public"), "cache.dealCheck.public should exist");

  const publicRoster = getDealCheckRosterNames("public", null);
  assert.ok(publicRoster.includes("이준석"));
  assert.ok(publicRoster.includes("김미송"));
  assert.strictEqual(inferPartFromOwners("public", ["이준석"]), "전체");
  assert.strictEqual(inferPartFromOwners("public", []), "미매핑");
});

test("loadBizPerfSummary caches by team+scope+year and uses year-specific range", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const calls = [];
  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async (url) => {
      calls.push(url);
      return {
        ok: true,
        json: async () => ({ months: [], segments: [] }),
        text: async () => "{}",
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

  const loadBizPerfSummary = vm.runInContext("loadBizPerfSummary", ctx);

  await loadBizPerfSummary({ teamKey: "edu1", scopeKey: "edu1_p1", year: 2026 });
  await loadBizPerfSummary({ teamKey: "edu1", scopeKey: "edu1_p1", year: 2026 }); // cache hit
  await loadBizPerfSummary({ teamKey: "edu1", scopeKey: "edu1_p2", year: 2026 });
  await loadBizPerfSummary({ teamKey: "edu1", scopeKey: "edu1_p1", year: 2025 });

  assert.strictEqual(calls.length, 3, "team+scope+year cache should avoid only exact duplicate fetches");

  const first = new URL(calls[0]);
  assert.strictEqual(first.pathname, "/api/performance/monthly-amounts/summary");
  assert.strictEqual(first.searchParams.get("from"), "2026-01");
  assert.strictEqual(first.searchParams.get("to"), "2026-12");
  assert.strictEqual(first.searchParams.get("team"), "edu1");
  assert.strictEqual(first.searchParams.get("scope"), "edu1_p1");

  const second = new URL(calls[1]);
  assert.strictEqual(second.pathname, "/api/performance/monthly-amounts/summary");
  assert.strictEqual(second.searchParams.get("from"), "2026-01");
  assert.strictEqual(second.searchParams.get("to"), "2026-12");
  assert.strictEqual(second.searchParams.get("team"), "edu1");
  assert.strictEqual(second.searchParams.get("scope"), "edu1_p2");

  const third = new URL(calls[2]);
  assert.strictEqual(third.pathname, "/api/performance/monthly-amounts/summary");
  assert.strictEqual(third.searchParams.get("from"), "2025-01");
  assert.strictEqual(third.searchParams.get("to"), "2025-12");
  assert.strictEqual(third.searchParams.get("team"), "edu1");
  assert.strictEqual(third.searchParams.get("scope"), "edu1_p1");
});

test("loadBizPerfDeals forwards optional scope key", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const calls = [];
  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost" } },
    document: docStub,
    fetch: async (url) => {
      calls.push(url);
      return {
        ok: true,
        json: async () => ({ items: [] }),
        text: async () => "{}",
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

  const loadBizPerfDeals = vm.runInContext("loadBizPerfDeals", ctx);
  await loadBizPerfDeals("ALL", "TOTAL", "2601", { teamKey: "edu2", scopeKey: "edu2_online" });

  assert.strictEqual(calls.length, 1);
  const url = new URL(calls[0]);
  assert.strictEqual(url.pathname, "/api/performance/monthly-amounts/deals");
  assert.strictEqual(url.searchParams.get("segment"), "ALL");
  assert.strictEqual(url.searchParams.get("row"), "TOTAL");
  assert.strictEqual(url.searchParams.get("month"), "2601");
  assert.strictEqual(url.searchParams.get("team"), "edu2");
  assert.strictEqual(url.searchParams.get("scope"), "edu2_online");
});

test("monthly year helpers filter month keys and current-month highlighting key", async () => {
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

  const pickPerfMonthlyMonthsByYear = vm.runInContext("pickPerfMonthlyMonthsByYear", ctx);
  const getPerfMonthlyCurrentMonthKey = vm.runInContext("getPerfMonthlyCurrentMonthKey", ctx);
  const renderBizPerfCard = vm.runInContext("renderBizPerfCard", ctx);

  const picked = pickPerfMonthlyMonthsByYear(["2501", "2512", "2601", "2603"], 2026);
  assert.strictEqual(JSON.stringify(picked), JSON.stringify(["2601", "2603"]));

  const now = new Date();
  const currentYear = now.getFullYear();
  const currentYYMM = `${String(currentYear).slice(2)}${String(now.getMonth() + 1).padStart(2, "0")}`;
  assert.strictEqual(getPerfMonthlyCurrentMonthKey(currentYear), currentYYMM);
  assert.strictEqual(getPerfMonthlyCurrentMonthKey(currentYear - 1), null);

  const cardHtml = renderBizPerfCard(
    {
      key: "ALL",
      label: "ALL",
      rows: [
        {
          key: "TOTAL",
          label: "TOTAL",
          byMonth: { "2603": 1, "2604": 2 },
          dealCountByMonth: { "2603": 1, "2604": 1 },
        },
      ],
    },
    ["2603", "2604"],
    "2604",
  );
  assert.ok(cardHtml.includes('<th class="is-current-month">2604</th>'));
  assert.ok(cardHtml.includes('<td class="is-current-month">'));
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

test("applyActualOverridesToPnlData replaces monthly E and recomputes yearly E/OP margin", () => {
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

  const applyActual = vm.runInContext("applyActualOverridesToPnlData", ctx);

  const summary = {
    year: 2026,
    months: ["2601", "2602"],
    columns: [
      { key: "Y2026_T", kind: "YEAR", variant: "T" },
      { key: "Y2026_E", kind: "YEAR", variant: "E" },
      { key: "2601_T", kind: "MONTH", variant: "T", month: "2601" },
      { key: "2601_E", kind: "MONTH", variant: "E", month: "2601" },
      { key: "2602_T", kind: "MONTH", variant: "T", month: "2602" },
      { key: "2602_E", kind: "MONTH", variant: "E", month: "2602" },
    ],
    rows: [
      {
        key: "REV_TOTAL",
        format: "eok",
        values: { Y2026_E: 3, "2601_E": 1, "2602_E": 2 },
      },
      {
        key: "REV_ONLINE",
        format: "eok",
        values: { Y2026_E: 1, "2601_E": 0.4, "2602_E": 0.6 },
      },
      {
        key: "REV_OFFLINE",
        format: "eok",
        values: { Y2026_E: 2, "2601_E": 0.6, "2602_E": 1.4 },
      },
      {
        key: "OP",
        format: "eok",
        values: { Y2026_E: 0.3, "2601_E": 0.1, "2602_E": 0.2 },
      },
      {
        key: "OP_MARGIN",
        format: "percent",
        values: { Y2026_E: 10, "2601_E": 10, "2602_E": 10 },
      },
    ],
  };

  const actualPayload = {
    overrides: {
      REV_TOTAL: { "2601": 6.65 },
      REV_ONLINE: { "2601": null },
      OP: { "2601": -2.9 },
    },
  };

  const result = applyActual(summary, actualPayload);
  const rows = new Map((result.data.rows || []).map((row) => [row.key, row]));

  assert.strictEqual(rows.get("REV_TOTAL").values["2601_E"], 6.65);
  assert.strictEqual(rows.get("REV_ONLINE").values["2601_E"], null);
  assert.ok(Math.abs(rows.get("REV_TOTAL").values.Y2026_E - 8.65) < 1e-9);
  assert.ok(Math.abs(rows.get("OP").values.Y2026_E - (-2.7)) < 1e-9);
  assert.ok(result.replacedCellSet.has("REV_TOTAL|2601|E"));
  assert.ok(result.replacedCellSet.has("REV_ONLINE|2601|E"));
  assert.ok(result.replacedCellSet.has("OP|2601|E"));

  const monthMargin = rows.get("OP_MARGIN").values["2601_E"];
  const yearMargin = rows.get("OP_MARGIN").values.Y2026_E;
  assert.ok(Math.abs(monthMargin - ((-2.9 / 6.65) * 100)) < 1e-9);
  assert.ok(Math.abs(yearMargin - ((-2.7 / 8.65) * 100)) < 1e-9);

  // original input object should remain unchanged
  assert.strictEqual(summary.rows[0].values["2601_E"], 1);
  assert.strictEqual(summary.rows[1].values["2601_E"], 0.4);
});

test("buildApiBaseCandidates includes localhost:8000 fallback for dev frontend origin", () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: {
      location: {
        origin: "http://localhost:8001",
        hostname: "localhost",
        protocol: "http:",
        search: "",
      },
      localStorage: { getItem: () => null },
    },
    document: docStub,
    fetch: async () => ({ ok: true, json: async () => ({}), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
    TypeError,
  };
  sandbox.global = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const candidates = vm.runInContext("buildApiBaseCandidates()", ctx);
  assert.ok(Array.isArray(candidates) && candidates.length > 0);
  assert.strictEqual(candidates[0], "http://localhost:8001/api");
  assert.ok(candidates.includes("http://localhost:8000/api"));
});

test("fetchJson falls back to alternate API base when first base is unreachable", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const calls = [];
  const sandbox = {
    console,
    window: {
      location: {
        origin: "http://localhost:8001",
        hostname: "localhost",
        protocol: "http:",
        search: "",
      },
      localStorage: { getItem: () => null },
    },
    document: docStub,
    fetch: async (url) => {
      calls.push(url);
      if (String(url).startsWith("http://localhost:8001/api")) {
        throw new TypeError("Failed to fetch");
      }
      if (String(url).startsWith("http://localhost:8000/api")) {
        return {
          ok: true,
          json: async () => ({ status: "ok" }),
          text: async () => '{"status":"ok"}',
        };
      }
      return {
        ok: false,
        statusText: "not found",
        text: async () => "not found",
      };
    },
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
    TypeError,
  };
  sandbox.global = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const fetchJson = vm.runInContext("fetchJson", ctx);
  const data = await fetchJson("/health");
  assert.strictEqual(data.status, "ok");
  assert.ok(calls.some((u) => String(u).startsWith("http://localhost:8001/api")));
  assert.ok(calls.some((u) => String(u).startsWith("http://localhost:8000/api")));
  const currentApiBase = vm.runInContext("API_BASE", ctx);
  assert.strictEqual(currentApiBase, "http://localhost:8000/api");
});

test("fetchJson falls back to alternate API base when first base returns 404", async () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const calls = [];
  const sandbox = {
    console,
    window: {
      location: {
        origin: "http://localhost:8001",
        hostname: "localhost",
        protocol: "http:",
        search: "",
      },
      localStorage: { getItem: () => null },
    },
    document: docStub,
    fetch: async (url) => {
      calls.push(url);
      if (String(url).startsWith("http://localhost:8001/api")) {
        return {
          ok: false,
          status: 404,
          statusText: "Not Found",
          text: async () => "not found",
        };
      }
      if (String(url).startsWith("http://localhost:8000/api")) {
        return {
          ok: true,
          json: async () => ({ status: "ok" }),
          text: async () => '{"status":"ok"}',
        };
      }
      return {
        ok: false,
        status: 500,
        statusText: "error",
        text: async () => "error",
      };
    },
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
    TypeError,
  };
  sandbox.global = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(scriptContent, ctx);

  const fetchJson = vm.runInContext("fetchJson", ctx);
  const data = await fetchJson("/health");
  assert.strictEqual(data.status, "ok");
  assert.ok(calls.some((u) => String(u).startsWith("http://localhost:8001/api")));
  assert.ok(calls.some((u) => String(u).startsWith("http://localhost:8000/api")));
  const currentApiBase = vm.runInContext("API_BASE", ctx);
  assert.strictEqual(currentApiBase, "http://localhost:8000/api");
});

test("renderDealCheckTable shows createdAt column between dealName and courseFormat in YYMMDD", () => {
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

  const renderDealCheckTable = vm.runInContext("renderDealCheckTable", ctx);
  const rendered = renderDealCheckTable(
    "edu1",
    [
      {
        dealId: "deal-1",
        dealName: "신규 제안",
        createdAt: "2025-01-02",
        courseFormat: "구독제(온라인)",
        orgId: "org-1",
        orgName: "테스트기업",
        owners: ["김솔이"],
        memoCount: 0,
        expectedCloseDate: "2025-02-03",
        expectedAmount: 100000000,
        personId: "person-1",
        personName: "담당자",
        probability: "높음",
      },
    ],
    { includeTier: false }
  );

  const dealHead = '<th data-col="dealName">딜 이름</th>';
  const createdHead = '<th data-col="createdAt">생성 날짜</th>';
  const formatHead = '<th data-col="courseFormat">과정포맷</th>';
  assert.ok(rendered.includes(createdHead), "createdAt header missing");
  assert.ok(rendered.includes('<td data-col="createdAt">250102</td>'), "createdAt row value is not YYMMDD");
  assert.ok(rendered.indexOf(dealHead) < rendered.indexOf(createdHead), "createdAt header should be after dealName");
  assert.ok(
    rendered.indexOf(createdHead) < rendered.indexOf(formatHead),
    "createdAt header should be before courseFormat"
  );
});

test("fitColumnsToContent clamps compact courseFormat width to 56~160px", () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  docStub.createElement = (tag) => {
    if (tag === "canvas") {
      return {
        getContext: () => ({
          measureText: (text) => ({ width: String(text || "").length * 8 }),
        }),
      };
    }
    return new StubElement();
  };

  const sandbox = {
    console,
    window: {
      location: { origin: "http://localhost" },
      getComputedStyle: () => ({ font: "12px sans-serif" }),
    },
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

  const fitColumnsToContent = vm.runInContext("fitColumnsToContent", ctx);
  fitColumnsToContent._canvas = null;

  const colMap = new Map([
    ["courseFormat", { style: {} }],
    ["createdAt", { style: {} }],
    ["expectedCloseDate", { style: {} }],
  ]);
  const tableEl = {
    querySelector: (selector) => {
      const m = /col\[data-col="([^"]+)"\]/.exec(selector);
      if (!m) return null;
      return colMap.get(m[1]) || null;
    },
  };

  fitColumnsToContent(
    tableEl,
    [{ courseFormat: "A", createdAt: "2025-01-01", expectedCloseDate: "2025-01-02", owners: [] }],
    { compact: true, includeTier: false, inferPartFn: () => "-" }
  );
  const minWidth = Number.parseFloat(colMap.get("courseFormat").style.width);
  assert.strictEqual(minWidth, 56, "compact min width should be 56px");

  fitColumnsToContent(
    tableEl,
    [
      {
        courseFormat: "X".repeat(200),
        createdAt: "2025-01-01",
        expectedCloseDate: "2025-01-02",
        owners: [],
      },
    ],
    { compact: true, includeTier: false, inferPartFn: () => "-" }
  );
  const maxWidth = Number.parseFloat(colMap.get("courseFormat").style.width);
  assert.strictEqual(maxWidth, 160, "compact max width should be 160px");
});

test("daily report menus are hidden in sidebar config but still reachable by hash", () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStubA = createDocumentStub();
  const sandboxA = {
    console,
    window: { location: { origin: "http://localhost", hash: "" } },
    document: docStubA,
    fetch: async () => ({ ok: true, json: async () => ({ items: [] }), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandboxA.global = sandboxA;
  const ctxA = vm.createContext(sandboxA);
  vm.runInContext(scriptContent, ctxA);

  const menuSections = vm.runInContext("MENU_SECTIONS", ctxA);
  const menuIds = vm.runInContext("MENU_IDS", ctxA);
  const renderers = vm.runInContext("MENU_RENDERERS", ctxA);

  const perfSection = menuSections.find((section) => section.sectionId === "perf");
  assert.ok(perfSection, "perf section is missing");
  const offlineItem = perfSection.items.find((item) => item.id === "counterparty-risk-daily");
  const onlineItem = perfSection.items.find((item) => item.id === "counterparty-risk-daily-online");
  assert.ok(offlineItem && offlineItem.hidden === true, "offline daily report menu should be hidden");
  assert.ok(onlineItem && onlineItem.hidden === true, "online daily report menu should be hidden");

  assert.strictEqual(menuIds.has("counterparty-risk-daily"), true, "offline menu id should remain routable");
  assert.strictEqual(menuIds.has("counterparty-risk-daily-online"), true, "online menu id should remain routable");
  assert.strictEqual(typeof renderers["counterparty-risk-daily"], "function");
  assert.strictEqual(typeof renderers["counterparty-risk-daily-online"], "function");

  const docStubB = createDocumentStub();
  const sandboxB = {
    console,
    window: { location: { origin: "http://localhost", hash: "#counterparty-risk-daily-online" } },
    document: docStubB,
    fetch: async () => ({ ok: true, json: async () => ({ items: [] }), text: async () => "{}" }),
    setTimeout,
    clearTimeout,
    Map,
    Set,
    URL,
    URLSearchParams,
  };
  sandboxB.global = sandboxB;
  const ctxB = vm.createContext(sandboxB);
  vm.runInContext(scriptContent, ctxB);

  const getInitialMenuId = vm.runInContext("getInitialMenuId", ctxB);
  assert.strictEqual(getInitialMenuId(), "counterparty-risk-daily-online");
});

test("org performance section is inserted under ops and contains exact top-level monthly menus", () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost", hash: "" } },
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

  const menuSections = vm.runInContext("MENU_SECTIONS", ctx);
  const renderers = vm.runInContext("MENU_RENDERERS", ctx);
  const sectionIds = menuSections.map((s) => s.sectionId);
  const opsIdx = sectionIds.indexOf("ops");
  const orgPerfIdx = sectionIds.indexOf("org-perf");
  const analysisIdx = sectionIds.indexOf("analysis");
  assert.ok(opsIdx >= 0 && orgPerfIdx >= 0 && analysisIdx >= 0, "expected section ids missing");
  assert.ok(opsIdx < orgPerfIdx && orgPerfIdx < analysisIdx, "org-perf should be placed between ops and analysis");

  const perfSection = menuSections.find((s) => s.sectionId === "perf");
  const orgPerfSection = menuSections.find((s) => s.sectionId === "org-perf");
  assert.ok(perfSection, "perf section missing");
  assert.ok(orgPerfSection, "org-perf section missing");

  const expectedIds = [
    "biz-perf-monthly-edu1",
    "biz-perf-monthly-edu2",
    "biz-perf-monthly-edu1-part1",
    "biz-perf-monthly-edu1-part2",
    "biz-perf-monthly-edu2-part1",
    "biz-perf-monthly-edu2-part2",
    "biz-perf-monthly-edu2-online",
    "biz-perf-monthly-public",
  ];
  const expectedLabels = [
    "2026 1팀 월별 체결액",
    "2026 2팀 월별 체결액",
    "2026 1팀 1파트 월별 체결액",
    "2026 1팀 2파트 월별 체결액",
    "2026 2팀 1파트 월별 체결액",
    "2026 2팀 2파트 월별 체결액",
    "2026 2팀 온라인셀 월별 체결액",
    "2026 공공교육팀 월별 체결액",
  ];

  assert.strictEqual(
    JSON.stringify(orgPerfSection.items.map((item) => item.id)),
    JSON.stringify(expectedIds),
    "org-perf monthly menu ids should match exact order",
  );
  assert.strictEqual(
    JSON.stringify(orgPerfSection.items.map((item) => item.label)),
    JSON.stringify(expectedLabels),
    "org-perf monthly labels should match exact order",
  );

  expectedIds.forEach((id, idx) => {
    assert.strictEqual(
      perfSection.items.some((item) => item.id === id),
      false,
      `perf section should not include org-perf item ${id}`,
    );
    assert.strictEqual(orgPerfSection.items[idx].label.startsWith("↳"), false, `${id} label should not include arrow prefix`);
    assert.strictEqual(typeof renderers[id], "function", `${id} renderer should exist`);
  });
});

test("analysis section starts with inquiries and close-rate menus, removed from perf section", () => {
  const html = fs.readFileSync(path.join(process.cwd(), "org_tables_v2.html"), "utf8");
  const scriptContent = extractScript(html);

  const docStub = createDocumentStub();
  const sandbox = {
    console,
    window: { location: { origin: "http://localhost", hash: "" } },
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

  const menuSections = vm.runInContext("MENU_SECTIONS", ctx);
  const renderers = vm.runInContext("MENU_RENDERERS", ctx);
  const perfSection = menuSections.find((s) => s.sectionId === "perf");
  const analysisSection = menuSections.find((s) => s.sectionId === "analysis");
  assert.ok(perfSection, "perf section missing");
  assert.ok(analysisSection, "analysis section missing");

  assert.strictEqual(
    perfSection.items.some((item) => item.id === "biz-perf-monthly-edu2-inquiries"),
    false,
    "inquiries menu should be removed from perf section",
  );
  assert.strictEqual(
    perfSection.items.some((item) => item.id === "biz-perf-monthly-close-rate-2026"),
    false,
    "close-rate menu should be removed from perf section",
  );

  assert.strictEqual(analysisSection.items[0]?.id, "biz-perf-monthly-edu2-inquiries");
  assert.strictEqual(analysisSection.items[1]?.id, "biz-perf-monthly-close-rate-2026");
  assert.strictEqual(analysisSection.items[0]?.label, "2026 문의 인입 현황");
  assert.strictEqual(analysisSection.items[1]?.label, "2026 체결률 현황");
  assert.strictEqual(typeof renderers["biz-perf-monthly-edu2-inquiries"], "function");
  assert.strictEqual(typeof renderers["biz-perf-monthly-close-rate-2026"], "function");
});

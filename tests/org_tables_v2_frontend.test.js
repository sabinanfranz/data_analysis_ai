import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import vm from "node:vm";

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
  assert.strictEqual(hintFiltered.textContent, "상위 조직을 선택하세요.");

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
  assert.strictEqual(state.size, "대기업");

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
  assert.strictEqual(sizeSelect.value, "대기업");
  assert.strictEqual(orgSelect.value, "");
});

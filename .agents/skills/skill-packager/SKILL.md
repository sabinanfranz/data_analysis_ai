---
name: skill-packager
description: Use when converting an incoming markdown knowledge doc into a repo-scoped Codex Skill under .agents/skills/* (SKILL.md + references/* + optional agents/openai.yaml) and updating/creating AGENTS.md with a minimal trigger line, while preserving this repo's SSOT conventions (snapshot→SQLite→FastAPI→org_tables_v2.html, docs/llm_context contracts, and cache/DB-path invariants).
---

## Goal
Package a markdown "knowledge document" into a **repo-scoped Codex Skill** using this repo's conventions:
- **Skill location:** `.agents/skills/<skill-name>/`
- **Progressive disclosure:** keep `SKILL.md` short (trigger + procedure). Put long-form material under `references/`.
- **Repo SSOT constraints (must be reflected in produced docs):**
  - Snapshot/DB SSOT: `salesmap_first_page_snapshot.py`, `salesmap_latest.db`, `start.sh`
  - API SSOT: `dashboard/server/org_tables_api.py` (thin) + `dashboard/server/database.py` (logic/aggregation)
  - Frontend SSOT: `org_tables_v2.html` (static, menu/render/cache contract)
  - Contract docs SSOT: `docs/llm_context/*` (00~14) + (PJT2) `docs/llm_context_pjt2/*`

## When to use (Trigger)
Invoke this skill if the task includes any of:
- "지식 문서 / knowledge doc / reference doc"를 스킬화
- `.agents/skills/`, `SKILL.md`, `references/`, `AGENTS.md`
- "Codex Skill", "repo-scoped skill", "progressive disclosure"
- "스킬 트리거 문장(description)", "full content 출력", "스킬 패키징"

## Required steps (Procedure)
1) **Collect inputs** (do not guess):
   - `SKILL_NAME` (kebab-case), `SCOPE_ONE_LINER` (single-line)
   - `REFERENCE_SLUG` (e.g. `frontend_org_tables_v2_contract.md`)
   - raw knowledge markdown (`KNOWLEDGE_DOC_MD`)
   - optional: repo philosophy summary (what MUST NOT break)
   - optional: whether `AGENTS.md` exists, whether `.agents/skills` exists
2) **Improve the knowledge doc** (reference quality):
   - Keep factual claims grounded; if uncertain, mark "확인 필요/TODO".
   - Restructure for dev/ops readability:
     - TL;DR (<=10 lines)
     - When/Why (repo SSOT + invariants)
     - Key concepts / Vocabulary (use repo's terms)
     - Practical patterns (how we do it here)
     - Do / Don't
     - Version/changes
     - Troubleshooting / Verification commands
3) **Apply progressive disclosure**:
   - `SKILL.md` must be short: triggers + required procedure + output format + verification.
   - Put the improved long-form doc into `references/<REFERENCE_SLUG>`.
   - Create `references/README.md` as an index/reading order.
   - If too long, optionally split into multiple files and keep an index, but ALWAYS keep `<REFERENCE_SLUG>` as either:
     - the compiled overview, or
     - the "00_index.md" equivalent that links to the parts.
4) **Create/Update files** (docs/skills only + optional AGENTS.md):
   - `.agents/skills/<SKILL_NAME>/SKILL.md`
   - `.agents/skills/<SKILL_NAME>/references/README.md`
   - `.agents/skills/<SKILL_NAME>/references/<REFERENCE_SLUG>`
   - optional: `.agents/skills/<SKILL_NAME>/agents/openai.yaml` (ONLY if explicitly needed)
   - `AGENTS.md`: create if missing; else minimal 1-2 line patch only.
5) **AGENTS.md trigger rule** (minimal, no bloat):
   - Add ONE concise line (avoid duplicates) that says:
     - "If a task involves packaging knowledge docs into a Codex Skill (SKILL.md/references/AGENTS.md), always invoke $<SKILL_NAME> and follow its references."
6) **Output format (must match exactly)**:
   - Plan (short)
   - `## File Tree`
   - `## Files` (FULL CONTENT for each file; no diffs)
   - `## AGENTS.md Patch Summary` (<=5 lines)
   - `## Validation` (commands to verify)

## Output format (exact)
- Plan (short)
- File Tree
- Files (full content)
- AGENTS.md Patch Summary
- Validation commands

## Reference
- `references/README.md`
- `references/skill_packager.md`

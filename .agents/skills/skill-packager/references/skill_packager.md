---
title: skill-packager 상세 가이드 (repo-scoped Codex Skills)
last_synced: 2026-02-08
---

# Purpose
이 문서는 "마크다운 지식 문서(knowledge doc)"를 이 레포에서 재사용 가능한 **repo-scoped Codex Skill**로 변환하는 표준 절차를 제공합니다.

이 레포의 핵심 목표는:
- 문서의 재사용성과 탐색성(짧은 SKILL.md + 긴 references)
- SSOT(단일 진실) 유지
- 변경 시 안전한 검증(테스트/런북) 가능성
입니다.

---

# Core Conventions (Must Follow)
## 1) Skill 위치 / 구조
- `.agents/skills/<skill-name>/SKILL.md`
- `.agents/skills/<skill-name>/references/*`

원칙:
- `SKILL.md`는 **짧고 실행 중심**: 언제 쓰는지(Trigger) + 어떻게 하는지(Procedure) + 출력 포맷 + 검증.
- 긴 배경/근거/예시는 `references/`로 보냅니다.

## 2) Repo SSOT를 절대 덮어쓰지 않기
이 레포는 이미 다음 SSOT가 존재합니다. Skill 문서는 이를 "대체"하지 않고 "작업 지침으로 연결"해야 합니다.

- 시스템 흐름: 스냅샷(SQLite) → FastAPI → 정적 프런트
- 문서 SSOT: `docs/llm_context/*` (00~14)
- 코드 SSOT(경로/책임):
  - snapshot: `salesmap_first_page_snapshot.py`, 배포: `start.sh`
  - API 라우터: `dashboard/server/org_tables_api.py` (thin)
  - 로직/집계: `dashboard/server/database.py` (heavy)
  - 프런트: `org_tables_v2.html` (single static file)

규칙:
- Skill에서 사실을 단정할 때는 **근거 파일(SSOT)을 링크하거나 명시**합니다.
- 불확실하면 "확인 필요/TODO"로 남기고, 검증 커맨드를 제시합니다.

---

# Packaging Procedure (Detailed)
## Step 1) Inputs 수집 (추정 금지)
아래 4가지를 반드시 확보합니다.
- `SKILL_NAME` (kebab-case)
- `SCOPE_ONE_LINER` (한 줄 설명)
- `REFERENCE_SLUG` (references에 저장할 md 파일명)
- `KNOWLEDGE_DOC_MD` (원문 마크다운)

추가로 있으면 좋은 것:
- 이 문서가 "깨면 안 되는 불변조건"에 직접 관련되는지 여부
- 문서가 어느 SSOT(00~14 또는 pjt2 01~10)와 연관되는지

## Step 2) Knowledge Doc 품질 개선 (reference 품질로)
아래 포맷으로 재구성합니다(권장):
- TL;DR (10줄 이하)
- When/Why: 어떤 상황에서 쓰는지 + 왜 필요한지
- Repo-specific invariants: 이 레포에서만 중요한 불변조건/주의점
- How-to / Patterns: 실제로 뭘 하면 되는지 (절차/체크리스트)
- Do / Don't: 금지/권장
- Troubleshooting: 흔한 실패/원인/해결
- Verification: 최소 검증 커맨드 (curl, unittest, node --test 등)

문서가 길면 섹션/표/리스트로 쪼개되, "운영자가 바로 실행할 수 있는 절차"를 우선합니다.

## Step 3) Progressive Disclosure 적용
- `SKILL.md`에는 "요약 + 실행 절차"만 둡니다.
- 상세 내용/배경/예시는 `references/<REFERENCE_SLUG>`로 이동합니다.
- references/README.md에는 "읽기 순서"와 "연관 SSOT 링크"를 둡니다.

## Step 4) 파일 생성/업데이트
생성해야 할 파일:
- `.agents/skills/<SKILL_NAME>/SKILL.md`
- `.agents/skills/<SKILL_NAME>/references/README.md`
- `.agents/skills/<SKILL_NAME>/references/<REFERENCE_SLUG>`

주의:
- 이 skill-packager의 기본 정책은 **문서/스킬만 생성**입니다.
- 코드 수정(backend/frontend/tests)은 별도 명시가 없는 한 하지 않습니다.

## Step 5) AGENTS.md에 "최소 트리거 라인"만 추가
- 기존 AGENTS.md가 있으면 1~2줄만 추가하고, 중복 라인은 피합니다.
- 핵심 문장(한 줄)만 삽입합니다:

예시:
> If a task involves packaging knowledge docs into a Codex Skill (SKILL.md/references/AGENTS.md), always invoke $skill-packager and follow its references.

---

# Output Format Contract (for the assistant)
Skill-packager가 수행한 결과를 출력할 때는 **diff 금지**, "파일 전체 내용"만 제공합니다.

반드시 이 순서를 지킵니다:
1) Plan (short)
2) File Tree
3) Files (full content)
4) AGENTS.md Patch Summary (<=5 lines)
5) Validation commands

---

# Validation Checklist (Recommended)
아래 중 최소 3개를 제시합니다:
- 파일 존재 확인:
  - `test -f AGENTS.md`
  - `test -f .agents/skills/<SKILL_NAME>/SKILL.md`
  - `test -f .agents/skills/<SKILL_NAME>/references/<REFERENCE_SLUG>`
- 링크/경로 sanity check:
  - `rg "docs/llm_context" -n .agents/skills/<SKILL_NAME>`
- 마크다운 빠른 렌더/가독성 점검(수동):
  - 제목/섹션 누락 여부
  - TL;DR 10줄 이하인지
  - Verification 커맨드가 실제로 실행 가능한지

---

# Gotchas (이 레포에서 특히 자주 터지는 것들)
- "DB 교체 후에도 UI가 바뀌지 않음": org_tables_v2는 화면별 Map 캐시를 가지며 무효화가 없어서 새로고침이 필요합니다.
- "라우터에 로직이 커짐": 이 레포는 org_tables_api는 thin, database.py에 로직 집중이라는 관성이 강합니다. Skill 문서에서 이 경계를 흐리지 마세요.
- "계약/테스트 불일치": API/프런트/테스트가 기능별로 강결합이라, 문서만 업데이트하면 실제는 깨진 상태가 되기 쉽습니다. Verification에 테스트 실행 커맨드를 항상 포함하세요.

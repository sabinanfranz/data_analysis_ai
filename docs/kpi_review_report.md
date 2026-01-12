---
title: KPI Review Report (Chunks 1~3)
last_synced: 2026-01-12
sync_source:
  - build_kpi_review_report.py
  - templates/kpi_review_report.template.html
  - data/existing_orgs_2025_eval.txt
---

## Purpose
- 2025 성과평가용 개인 KPI 검수 리포트를 **정적 HTML 1파일**로 생성하고, 브라우저에서 담당자별 KPI 계산/제외/내보내기까지 수행하는 흐름(Chunk 1~3 완성)을 기록한다.

## Behavioral Contract
- **생성**: `python build_kpi_review_report.py --db <db> --out <path> --existing-orgs <file> --years 2024,2025` 실행 시 템플릿을 읽어 `window.__DATA__`에 JSON을 인라인 주입한 단일 HTML을 생성한다.
- **데이터 추출**: deal 테이블에서 Convert 상태 제거 후, `createdAt`/`contractDate` 연도가 `years` 리스트에 포함되면 포함한다. 연도 파싱은 문자열 시작 `YYYY`. organization 조인 시 `organization."이름"` 우선, 없으면 organizationId→dealId 순으로 대체. net% 컬럼은 PRAGMA로 `netPercent→net→NET→net%→NET%→공헌이익률→공헌이익률(%)→공헌이익률 %` 순으로 탐지하며 없으면 `meta.netPercentColumn="__NONE__"`.
- **UI(브라우저)**:
  - 상단 담당자 드롭다운(ALL 포함). ALL은 모든 담당자 제외내역 union을 표시하며 편집은 비활성화.
  - 탭1 KPI 요약: 2024/2025 × 전체/온라인/비온라인 + Δ. 체결률은 리드연도 기준 (Won/전체), 금액/공헌이익률/리텐션/업셀은 체결연도 Won 기준, 비온라인 공헌이익률은 net% 단순 평균, 온라인은 100%.
  - 탭2 과정포맷 분석: 연도 토글(기본 2025), 과정포맷별 리드/체결 성과, 온라인 포맷 3종은 공헌이익률 100% 처리.
  - 탭3 딜 리스트: owner 필터 후 Convert 제외, 제외 체크박스 제공(ALL에서는 편집 불가). 제외 시 즉시 KPI/과정포맷/탭4 갱신.
  - 탭4 제외 내역: 현재 owner의 제외된 딜 목록 표시, 개별 복구 가능(ALL은 복구 비활성). reason/note 필드는 표시만 하고 빈 문자열로 export.
- **Exclude/저장 규칙**:
  - `excludedSet=Set<dealId>`로 관리하며 KPI/포맷 계산에서 제외.
  - localStorage 키: `kpi_review::2024_2025::<dataGeneratedAt>::excludedDealIds::<ownerName>`(dataGeneratedAt 없으면 generatedAt).
  - owner 변경 시 해당 키를 로드, ALL은 모든 owner 키 union으로 로드(편집 불가).
- **Export/Import**:
  - 요약 CSV: `kpi_summary_<owner>_YYYYMMDD.csv`(UTF-8 BOM), 탭1과 동일 지표 raw 값(률은 %숫자).
  - 제외내역 JSON: `exclusions_<owner>_YYYYMMDD.json` with `{report:"2025성과평가_개인KPI", ownerName, generatedAt, excluded:[{dealId,reason,note,ts}]}`. reason/note는 빈 문자열로 기록.
  - 가져오기: 현재 owner와 JSON의 ownerName이 일치할 때만 적용, report 필드 검사. 가져오면 excludedSet+localStorage 갱신 후 재렌더.
- **초기화**: 현재 owner의 excludedSet을 비워 localStorage에서 삭제(ALL에서는 비활성 안내).

## Invariants (Must Not Break)
- HTML은 단일 파일이며 외부 fetch/CDN 없이 더블클릭 실행이 가능해야 한다.
- `window.__DATA__` 스키마는 Chunk1과 동일하게 유지하며, `generatedAt`/`dataGeneratedAt`/years/onlineFormats/existingOrgKeys/deals/meta를 포함한다.
- Convert 상태는 모든 지표/리스트에서 제외된다.
- 체결률 분모는 전체 딜(Lead 기준), 금액/공헌이익률/리텐션/업셀은 체결연도 Won 기준이며 비온라인 공헌이익률은 net% 단순 평균(금액가중 금지), 온라인은 1.0(100%).
- localStorage 키 버전에 dataGeneratedAt을 포함해 DB 교체 시 이전 제외내역이 섞이지 않는다.
- ALL 모드는 제외 union 조회만 허용하며 편집/초기화/가져오기는 개별 owner에서만 허용한다.
- CSV/JSON 파일명 규칙과 JSON 포맷(report/ownerName/fields)이 어긋나면 안 된다.

## Coupling Map
- 빌더/템플릿: `build_kpi_review_report.py`, `templates/kpi_review_report.template.html`.
- 입력 데이터: `salesmap_latest.db`(`deal`/`organization`), `data/existing_orgs_2025_eval.txt`.
- 결과물: CLI가 생성하는 단일 HTML 파일(기본 파일명 `2025성과평가_개인KPI_검수용_<years>_<today>.html`).

## Edge Cases & Failure Modes
- DB 경로/Existing orgs/템플릿 파일이 없으면 빌더가 예외로 중단된다.
- deal 테이블이나 필수 컬럼(dealId/owner/status)이 없으면 FriendlySchemaError로 시도한 후보+실제 컬럼을 안내하며 실패한다.
- 연도 파싱 실패/누락 건수는 meta에 기록되며, 해당 딜은 연도 필터에 포함되지 않는다.
- JSON import 시 ownerName 불일치 또는 report 필드가 다르면 적용하지 않고 경고한다.
- ALL 모드에서 제외를 편집하려 하면 경고 후 무시된다.

## Verification
- `python build_kpi_review_report.py --db salesmap_latest.db --out /tmp/report.html` 실행 후 `/tmp/report.html`을 열어 탭1~4가 모두 노출되고 JS 오류가 없는지 확인한다.
- 담당자 선택 후 딜 제외 체크 시 탭1/탭2 수치가 즉시 변경되는지 확인한다.
- 새로고침 후 제외 상태가 localStorage에서 복원되는지 확인한다.
- CSV/JSON 내보내기 버튼으로 파일이 다운로드되고, JSON 가져오기로 동일 owner에 제외 상태가 적용되는지 확인한다.
- ALL 모드에서 체크박스/초기화/가져오기가 비활성 안내로 막히는지 확인한다.
- `meta.dealCountBeforeFilters`→Convert 필터→연도 필터 카운트가 실제 딜 수와 일치하는지 spot-check한다.
- net% 컬럼이 없는 DB에서 `meta.netPercentColumn="__NONE__"`인지, 있는 DB에서는 탐지된 컬럼명이 기록되는지 확인한다.

## QA Checklist (필수)
- [ ] Convert 딜이 어디 표/리스트에도 보이지 않는가?
- [ ] 체결률 분모에 Lost/SQL 등이 포함되고 Won만 분모로 쓰지 않는가?
- [ ] 계약일 없는 Won 딜이 체결액/리텐션/업셀 계산에 섞이지 않는가?
- [ ] 비온라인 공헌이익률이 AVG(net%)로 계산되는가(금액가중 아님)?
- [ ] 온라인 3포맷 공헌이익률이 100%로 처리되는가?
- [ ] 딜 제외 체크 시 KPI/과정포맷 표가 즉시 변하는가?
- [ ] 새로고침해도 제외 상태가 복원되는가(localStorage)?
- [ ] CSV/JSON 내보내기 파일이 정상 다운로드되는가?
- [ ] JSON import가 현재 owner에만 적용되는가?

## Refactor-Planning Notes (Facts Only)
- 컬럼 후보군이 코드 내 상수로만 존재해 새로운 DB 스키마 대응 시 후보 목록을 업데이트해야 한다.
- 제외 사유/메모는 현재 빈 문자열로만 export/import되며, 추후 localStorage 구조를 변경해야 저장이 가능하다.
- ALL 모드 편집은 의도적으로 제한되어 owner별 저장 충돌을 방지한다.

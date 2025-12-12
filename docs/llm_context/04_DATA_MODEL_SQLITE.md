# SQLite 데이터 모델 요약

## 1) DB 생성 주체와 생명주기
- 생성/교체 주체: `salesmap_first_page_snapshot.py` 스냅샷 스크립트가 Salesmap API를 호출해 데이터를 받아 `salesmap_latest.db`를 생성하거나 교체한다.
- 교체 방식: 임시 DB에 적재 → 체크포인트/백업 → 최종 파일로 교체(자세한 절차는 `docs/snapshot_pipeline.md` 참고).
- 웹폼 제출 내역은 후처리 단계에서 `webform_history` 테이블로 적재된다.
- FastAPI 서버는 이 DB를 직접 읽는다(캐시 없음). 새 스냅샷으로 교체하면 프런트는 새로고침해야 최신 데이터로 동작한다.

## 2) 테이블 목록(자동 추출 기준)
`sqlite_master` 기준 총 10개 테이블:  
`deal`, `lead`, `manifest`, `memo`, `organization`, `people`, `run_info`, `team`, `user`, `webform_history`.

## 3) 핵심 엔터티/운영 테이블 관계
- **organization** ↔ **people** ↔ **deal**
  - `organization.id` = `people.organizationId`
  - `people.id` = `deal.peopleId`, `deal.organizationId`는 조직에도 직접 연결
  - 주요 컬럼:  
    - organization: `id`, `이름`, `기업 규모`, `업종`, `업종 구분(대)/(중)`, `제출된 웹폼 목록`  
    - people: `id`, `organizationId`, `이름`, `소속 상위 조직`, `팀(명함/메일서명)`, `직급(명함/메일서명)`, `담당 교육 영역`, `이메일`, `전화`, `제출된 웹폼 목록`, utm/마케팅 동의 등  
    - deal: `id`, `peopleId`, `organizationId`, `이름`, `상태`, `금액`, `예상 체결액`, `계약 체결일`, `생성 날짜`, `과정포맷`, `카테고리`, `담당자` JSON 등 (다수 보조 컬럼 존재)
- **memo**
  - 다대1 링크: `dealId` 또는 `peopleId` 또는 `organizationId`로 연결(없으면 고아 메모).  
  - 컬럼: `text`, `ownerId`, `createdAt`, `updatedAt` 등.
- **webform_history**
  - 제출 이벤트 로그: `peopleId`, `organizationId`, `dealId`, `leadId`, `webFormId`, `createdAt`, `contents`.  
  - 백엔드에서 `peopleId + webFormId`를 키로 날짜 리스트를 만든다.
- **lead**
  - Salesmap 리드 원본. 현재 주요 흐름에서는 참조하지 않지만 스냅샷에 포함됨.
- **run_info / manifest**
  - 실행 정보와 테이블별 행/컬럼 카운트, 에러 로그를 저장. 스냅샷 메타 확인용.
- **user / team**
  - Salesmap 사용자/팀 메타데이터. 주요 화면에서는 직접 사용하지 않음.

## 4) 돈/날짜 컬럼 규칙
- 금액/숫자: `deal."금액"`, `"예상 체결액"` 등은 TEXT로 저장되며, 백엔드에서 `float`로 변환(`_to_number`). 프런트는 표시 시 1e8(억) 단위로 나눈 값을 소수 2자리로 표기(`formatAmount`).
- 날짜: 대부분 TEXT(ISO 비슷한 문자열)로 저장. 백엔드는 단순 슬라이싱(YYYY-MM-DD)으로 사용하며, webform_history도 날짜 문자열을 리스트/단일 값으로 반환. 표시는 `formatDate`로 `YYYY-MM-DD`까지만 보여준다.

## 5) 인덱스/성능 팁
- 현재 스키마에는 선언된 인덱스가 없다. 빈번히 조인/필터하는 컬럼에 인덱스를 고려할 수 있다(TODO):
  - `people.organizationId`, `deal.organizationId`, `deal.peopleId`
  - `memo.dealId`, `memo.peopleId`, `memo.organizationId`
  - `webform_history.peopleId`, `webform_history.webFormId`

## 6) 스키마 추출 방법(재현)
```bash
python3 - <<'PY'
import sqlite3, os
con = sqlite3.connect("salesmap_latest.db")
con.row_factory = sqlite3.Row
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("tables:", tables)
for t in tables:
    print("\\n==", t)
    for c in con.execute(f"PRAGMA table_info('{t}')"):
        print(f" - {c['name']} ({c['type']})")
PY
```

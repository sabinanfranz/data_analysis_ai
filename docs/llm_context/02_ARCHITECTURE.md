# 아키텍처 개요

## 1) 시스템 개요
- Salesmap API에서 조직/People/Deal/웹폼 데이터를 가져와 **스냅샷(SQLite)** 으로 저장한다.
- FastAPI 서버(`dashboard/server`)가 스냅샷 DB를 읽어 API(`/api/...`)를 제공한다.
- 프런트(`org_tables_v2.html`)가 API를 호출해 조직/People/Deal/상위 조직 JSON을 렌더링한다.
- 캐시는 프런트(JS Map) 단에서만 사용하며, 백엔드는 무상태로 DB를 직접 읽는다.
- 기본 DB 경로는 `salesmap_latest.db`이며, 존재하지 않으면 500 에러로 응답한다.

## 2) 컴포넌트 책임 분리
| 컴포넌트 | 역할/책임 | 주요 파일 |
| --- | --- | --- |
| 스냅샷 스크립트 | Salesmap API 호출 → SQLite 스냅샷 적재, 웹폼 제출 내역(webform_history) 후처리 | `salesmap_first_page_snapshot.py`, `snapshot_pipeline.md` |
| SQLite DB | 조직/People/Deal/메모/웹폼/히스토리 저장. FastAPI가 직접 읽음 | `salesmap_latest.db` |
| FastAPI 서버 | DB 조회/집계 API 제공(`/api`) | `dashboard/server/main.py`, `org_tables_api.py`, `database.py` |
| 프런트(정적 HTML) | API fetch → 표/모달/JSON 렌더, 클라이언트 캐시(Map) | `org_tables_v2.html`, `org_tables_v2.md` |
| LLM 컨텍스트 문서 | 동작/계약/흐름을 요약해 외부 LLM에 전달 | `docs/llm_context/*.md` |

## 3) 데이터 흐름
```mermaid
flowchart LR
  A[Salesmap API] --> B[스냅샷 스크립트<br/>salesmap_first_page_snapshot.py]
  B -->|SQLite 저장| C[salesmap_latest.db]
  C --> D[FastAPI 서버<br/>/api/*]
  D --> E[프런트 org_tables_v2.html<br/>(fetch/render)]
  E -->|요청/응답| D
```

### 단계별 설명
1. 스냅샷 스크립트가 Salesmap API를 호출해 조직/People/Deal/웹폼 제출 내역을 수집하고 `salesmap_latest.db`에 기록한다.
2. FastAPI(`dashboard/server/main.py`)가 기동되면 DB를 직접 읽어 `/api` 엔드포인트를 제공한다(예: `/api/orgs`, `/api/orgs/{id}/won-groups-json` 등).
3. 프런트(`org_tables_v2.html`)는 API Base(기본 `http://localhost:8000/api`, origin에 따라 자동 설정)로 fetch를 보내고, 응답을 표/모달/JSON으로 렌더링하며 클라이언트 캐시(Map)에 저장한다.
4. 캐시는 프런트에만 존재한다. DB 교체 시 프런트를 새로고침해야 최신 상태를 본다.

## 4) 운영 상 중요한 계약
- 기본 DB 경로: `salesmap_latest.db`(루트). 없으면 500 오류.
- API Base: 기본 `http://localhost:8000/api` (origin 사용 시 `/api` 접미).
- 조직 목록(`/api/orgs`): People 또는 Deal이 1건 이상 있는 조직만 반환, 2025년 Won 합계 내림차순 정렬(이름 순 보조).
- 상위 조직 JSON(`/api/orgs/{id}/won-groups-json`): webform id 미노출, 날짜 매핑, 메모 정제(전화/동의/utm 제거 등) 적용.
- 프런트 캐시 무효화 없음: 새 DB로 교체 시 브라우저 새로고침 필요.
- 자동 선택 없음: 초기/리셋 시 회사는 자동으로 선택되지 않으며 사용자가 선택해야 데이터 로드.

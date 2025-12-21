from fastapi import APIRouter, HTTPException, Query

from . import database as db
from .json_compact import compact_won_groups_json
from .statepath_engine import build_statepath

router = APIRouter(prefix="/api")


@router.get("/sizes")
def get_sizes() -> dict:
    """
    Distinct organization sizes.
    """
    try:
        return {"sizes": db.list_sizes()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orgs")
def get_organizations(
    size: str = Query("전체", description='조직 규모 필터 (예: "대기업", "전체")'),
    search: str | None = Query(None, description="조직명 검색어"),
    limit: int = Query(200, ge=1, le=500, description="최대 반환 수"),
    offset: int = Query(0, ge=0, description="시작 offset"),
) -> dict:
    try:
        items = db.list_organizations(size=size, search=search, limit=limit, offset=offset)
        return {"items": items}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orgs/{org_id}/memos")
def get_org_memos(org_id: str, limit: int = Query(100, ge=1, le=500)) -> dict:
    try:
        return {"items": db.get_org_memos(org_id=org_id, limit=limit)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orgs/{org_id}/people")
def get_org_people(
    org_id: str,
    has_deal: bool | None = Query(None, alias="hasDeal", description="딜 여부 필터"),
) -> dict:
    try:
        people = db.get_people_for_org(org_id=org_id, has_deal=has_deal)
        return {"items": people}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/people/{person_id}/deals")
def get_person_deals(person_id: str) -> dict:
    try:
        return {"items": db.get_deals_for_person(person_id=person_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/people/{person_id}/memos")
def get_person_memos(person_id: str, limit: int = Query(200, ge=1, le=500)) -> dict:
    try:
        return {"items": db.get_memos_for_person(person_id=person_id, limit=limit)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/deals/{deal_id}/memos")
def get_deal_memos(deal_id: str, limit: int = Query(200, ge=1, le=500)) -> dict:
    try:
        return {"items": db.get_memos_for_deal(deal_id=deal_id, limit=limit)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/rank/2025-deals")
def get_rank_2025_deals(
    size: str = Query("전체", description='조직 규모 필터 (예: "대기업", "전체")')
) -> dict:
    try:
        return {"items": db.get_rank_2025_deals(size=size)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/rank/mismatched-deals")
def get_rank_mismatched_deals(
    size: str = Query("대기업", description='조직 규모 필터 (예: "대기업", "전체")')
) -> dict:
    try:
        return {"items": db.get_mismatched_deals(size=size)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/rank/won-yearly-totals")
def get_rank_won_yearly_totals() -> dict:
    try:
        return {"items": db.get_won_totals_by_size()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/rank/2025/summary-by-size")
def get_rank_2025_summary_by_size(
    exclude_org_name: str = Query("삼성전자", description="합계에서 제외할 조직명 (정확히 일치)"),
    years: str = Query("2025,2026", description="콤마 구분 연도 리스트(예: 2025,2026)"),
) -> dict:
    try:
        years_list = [int(str(y).strip()) for y in (years.split(",") if years else []) if str(y).strip()]
        return db.get_rank_2025_summary_by_size(exclude_org_name=exclude_org_name, years=years_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/rank/2025-deals-people")
def get_rank_2025_deals_people(
    size: str = Query("대기업", description='조직 규모 필터 (예: "대기업", "전체")')
) -> dict:
    try:
        return {"items": db.get_rank_2025_deals_people(size=size)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/rank/2025-top100-counterparty-dri")
def get_rank_2025_top100_counterparty_dri(
    size: str = Query("대기업", description='조직 규모 필터 (예: "대기업", "전체")'),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0, description="org 목록 offset (limit 단위)"),
) -> dict:
    try:
        return db.get_rank_2025_top100_counterparty_dri(size=size, limit=limit, offset=offset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/rank/2025-counterparty-dri/detail")
def get_rank_counterparty_dri_detail(orgId: str = Query(...), upperOrg: str = Query(...)) -> dict:
    try:
        return db.get_rank_2025_counterparty_detail(org_id=orgId, upper_org=upperOrg)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/rank/won-industry-summary")
def get_rank_won_industry_summary(
    size: str = Query("전체", description='조직 규모 필터 (예: "대기업", "중견기업", "전체")')
) -> dict:
    try:
        return {"items": db.get_won_industry_summary(size=size)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orgs/{org_id}/won-summary")
def get_won_summary(org_id: str) -> dict:
    try:
        return {"items": db.get_won_summary_by_upper_org(org_id=org_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/orgs/{org_id}/won-groups-json")
def get_won_groups_json(org_id: str) -> dict:
    try:
        return db.get_won_groups_json(org_id=org_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orgs/{org_id}/won-groups-json-compact")
def get_won_groups_json_compact(org_id: str) -> dict:
    try:
        raw = db.get_won_groups_json(org_id=org_id)
        return compact_won_groups_json(raw)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orgs/{org_id}/statepath")
def get_statepath(org_id: str) -> dict:
    try:
        raw = db.get_won_groups_json(org_id=org_id)
        compact = compact_won_groups_json(raw)
        item = build_statepath(compact)
        return {"item": item}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/statepath/portfolio-2425")
def get_statepath_portfolio(
    segment: str = Query("전체", description="대기업/중견기업/중소기업/공공기관/대학교/기타/미입력"),
    legacySizeGroup: str | None = Query(None, alias="sizeGroup"),
    search: str | None = Query(None, description="조직명 검색"),
    sort: str = Query("won2025_desc"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    riskOnly: bool = False,
    hasOpen: bool = False,
    hasScaleUp: bool = False,
    companyDir: str = Query("all"),
    seed: str = Query("all"),
    rail: str = Query("all"),
    railDir: str = Query("all"),
    companyFrom: str = Query("all"),
    companyTo: str = Query("all"),
    cell: str = Query("all"),
    cellEvent: str = Query("all"),
) -> dict:
    try:
        filters = {
            "riskOnly": riskOnly,
            "hasOpen": hasOpen,
            "hasScaleUp": hasScaleUp,
            "companyDir": companyDir,
            "seed": seed,
            "rail": rail,
            "railDir": railDir,
            "companyFrom": companyFrom,
            "companyTo": companyTo,
            "cell": cell,
            "cellEvent": cellEvent,
        }
        chosen_segment = legacySizeGroup or segment
        return db.get_statepath_portfolio(
            size_group=chosen_segment,
            search=search,
            filters=filters,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orgs/{org_id}/statepath-2425")
def get_statepath_detail(org_id: str) -> dict:
    try:
        item = db.get_statepath_detail(org_id)
        if not item:
            raise HTTPException(status_code=404, detail="Organization not found")
        return {"item": item}
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orgs/{org_id}")
def get_org(org_id: str) -> dict:
    try:
        match = db.get_org_by_id(org_id)
        if not match:
            raise HTTPException(status_code=404, detail="Organization not found")
        return {"item": match}
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

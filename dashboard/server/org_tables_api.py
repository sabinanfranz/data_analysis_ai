from fastapi import APIRouter, HTTPException, Query

from . import database as db

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


@router.get("/rank/2025-deals-people")
def get_rank_2025_deals_people(
    size: str = Query("대기업", description='조직 규모 필터 (예: "대기업", "전체")')
) -> dict:
    try:
        return {"items": db.get_rank_2025_deals_people(size=size)}
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

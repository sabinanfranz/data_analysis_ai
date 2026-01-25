from __future__ import annotations

from .schema import GroupProgressInputV1, GroupProgressOutputV1


def fallback_output(payload: GroupProgressInputV1) -> GroupProgressOutputV1:
    summary = [
        f"{payload.scope.type} {payload.scope.key} 기준 리포트",
        f"타겟 합계: {int(payload.rollup.target_sum_2026 or 0):,}원, 실적: {int(payload.rollup.actual_sum_2026 or 0):,}원",
    ]
    diagnosis = ["상세 진단은 L2 구현 후 확장 예정입니다."]
    priorities = ["주요 무진행 카운터파티를 점검하세요.", "주간 액션 아이템을 정리하세요.", "담당자 미입력/데이터 품질 이슈를 먼저 해소하세요."]
    return GroupProgressOutputV1(
        as_of=payload.as_of,
        report_mode=payload.report_mode,
        scope=payload.scope,
        executive_summary=summary,
        problem_diagnosis=diagnosis,
        today_priorities=priorities,
        rollup=payload.rollup,
        llm_meta={"fallback_used": True},
    )

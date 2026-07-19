from __future__ import annotations

from app.schemas.report import ReportSummaryResponse


def fallback_report_narrative(summary: ReportSummaryResponse) -> dict[str, object]:
    overview = summary.overview
    score = overview.average_safety_score
    score_text = (
        "아직 계산 가능한 안전 점수가 없습니다."
        if score is None
        else f"평균 안전 점수는 {score:.1f}점입니다."
    )
    most_common_behavior = _most_common_behavior(summary.behavior_counts)
    behavior_text = (
        "위험 행동 기록이 없습니다."
        if most_common_behavior is None
        else f"가장 많이 기록된 위험 행동은 {most_common_behavior}입니다."
    )
    return {
        "title": "주행 안전 요약",
        "summary": (
            f"{summary.period.start}부터 {summary.period.end}까지 "
            f"{overview.total_sessions}회의 주행이 기록됐고, {score_text} {behavior_text}"
        ),
        "recommendations": [
            "반복적으로 감지되는 위험 행동의 경고 민감도를 우선 조정합니다.",
            "개입 후 행동이 바로 개선된 항목은 현재 전략을 유지합니다.",
            "반응 지연이 긴 항목은 더 짧고 명확한 안내 문구로 조정합니다.",
        ],
        "provider": "GEMINI",
        "fallback": True,
    }


def _most_common_behavior(counts: dict[str, int]) -> str | None:
    non_zero_counts = {key: value for key, value in counts.items() if value > 0}
    if not non_zero_counts:
        return None
    return max(non_zero_counts, key=non_zero_counts.get)

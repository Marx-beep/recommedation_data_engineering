from __future__ import annotations

from src.models import Recommendation


def rerank(recommendations: list[Recommendation], top_k: int) -> list[Recommendation]:
    recommendations.sort(key=lambda item: (item.score, item.retrieval_score), reverse=True)
    direction_counts: dict[str, int] = {}
    for item in recommendations:
        direction = item.candidate.research_directions[0] if item.candidate.research_directions else "其他"
        count = direction_counts.get(direction, 0)
        if count >= 2:
            item.score = max(0, item.score - 2)
        direction_counts[direction] = count + 1
    recommendations.sort(key=lambda item: (item.score, item.retrieval_score), reverse=True)
    selected = recommendations[:top_k]
    for rank, item in enumerate(selected, start=1):
        item.rank = rank
        item.recommendation_level = (
            "强烈推荐" if item.score >= 85 else "推荐" if item.score >= 70 else "潜力候选" if item.score >= 55 else "谨慎考虑"
        )
    return selected


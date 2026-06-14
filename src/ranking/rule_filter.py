from __future__ import annotations

from src.features.tag_schema import DEGREE_ORDER
from src.models import Candidate, JobProfile


def degree_satisfied(candidate: Candidate, profile: JobProfile) -> bool:
    return DEGREE_ORDER.get(candidate.degree, 0) >= DEGREE_ORDER.get(profile.degree_requirement, 0)


def apply_hard_filters(
    recalled: list[tuple[Candidate, float]], profile: JobProfile, strict_degree: bool
) -> list[tuple[Candidate, float]]:
    if not strict_degree:
        return recalled
    return [item for item in recalled if degree_satisfied(item[0], profile)]


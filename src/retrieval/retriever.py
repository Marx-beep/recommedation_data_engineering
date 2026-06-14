from __future__ import annotations

import math
import re
from collections import Counter

from src.models import Candidate, JobProfile


def _tokens(text: str) -> list[str]:
    english = re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    grams = [word[i : i + 2] for word in chinese for i in range(len(word) - 1)]
    return english + chinese + grams


def candidate_text(candidate: Candidate) -> str:
    structured_text = " ".join(
        [
            candidate.gpa_ranking,
            candidate.english_level,
            *candidate.competition_awards,
            *candidate.skill_certifications,
            *candidate.student_work,
            candidate.self_evaluation,
            candidate.resume_summary,
            *(item.summary for item in candidate.research_experience),
            *(tag for item in candidate.research_experience for tag in item.content_tags),
            *(item.summary for item in candidate.work_experience),
            *(tag for item in candidate.work_experience for tag in item.content_tags),
        ]
    )
    return " ".join(
        [
            candidate.major,
            *candidate.research_directions,
            *candidate.experimental_skills,
            *candidate.software_skills,
            candidate.project_experience,
            candidate.internship_experience,
            *candidate.industry_tags,
            *candidate.evidence,
            structured_text,
        ]
    )


def profile_text(profile: JobProfile) -> str:
    return " ".join(
        [
            profile.degree_requirement,
            *profile.research_directions,
            *profile.required_skills,
            *profile.preferred_outputs,
            profile.industry_direction,
        ]
    )


def cosine_similarity(left: str, right: str) -> float:
    a, b = Counter(_tokens(left)), Counter(_tokens(right))
    common = set(a) & set(b)
    numerator = sum(a[token] * b[token] for token in common)
    denominator = math.sqrt(sum(value * value for value in a.values())) * math.sqrt(
        sum(value * value for value in b.values())
    )
    return numerator / denominator if denominator else 0.0


def retrieve(profile: JobProfile, candidates: list[Candidate], top_n: int = 10) -> list[tuple[Candidate, float]]:
    query = profile_text(profile)
    scored = [(candidate, cosine_similarity(query, candidate_text(candidate))) for candidate in candidates]
    return sorted(scored, key=lambda item: item[1], reverse=True)[:top_n]

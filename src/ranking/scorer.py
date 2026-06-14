from __future__ import annotations

from src.models import Candidate, JobProfile, Recommendation, ScoreBreakdown
from src.ranking.rule_filter import degree_satisfied


def _overlap(required: list[str], actual: list[str]) -> tuple[list[str], list[str]]:
    matched = [item for item in required if any(item.lower() in value.lower() or value.lower() in item.lower() for value in actual)]
    return matched, [item for item in required if item not in matched]


def score_candidate(candidate: Candidate, profile: JobProfile, retrieval_score: float) -> Recommendation:
    matched_research, missing_research = _overlap(profile.research_directions, candidate.research_directions)
    all_skills = candidate.experimental_skills + candidate.software_skills
    matched_skills, missing_skills = _overlap(profile.required_skills, all_skills)

    research = round(25 * len(matched_research) / max(1, len(profile.research_directions)))
    skills = round(25 * len(matched_skills) / max(1, len(profile.required_skills)))
    education = 15 if degree_satisfied(candidate, profile) else 5
    outputs = min(20, candidate.paper_count * 3 + candidate.patent_count * 2 + (4 if candidate.project_experience else 0))
    industry = 0
    if profile.industry_direction:
        industry = 12 if profile.industry_direction in candidate.industry_tags else 4
    elif candidate.internship_experience:
        industry = 10
    else:
        industry = 7

    if not profile.research_directions:
        research = round(retrieval_score * 25)
    if not profile.required_skills:
        skills = round(retrieval_score * 20) + 5

    breakdown = ScoreBreakdown(
        research=research,
        skills=skills,
        education=education,
        outputs=outputs,
        industry=industry,
    )
    score = sum(breakdown.model_dump().values())
    reasons = []
    if matched_research:
        reasons.append(f"研究方向匹配：{'、'.join(matched_research)}")
    if matched_skills:
        reasons.append(f"核心技能覆盖：{'、'.join(matched_skills)}")
    if candidate.paper_count:
        reasons.append(f"科研产出扎实：SCI 论文 {candidate.paper_count} 篇")
    if candidate.internship_experience:
        reasons.append("具备企业研发或工艺实践经历")
    weaknesses = []
    if missing_research:
        weaknesses.append(f"未明确体现研究方向：{'、'.join(missing_research)}")
    if missing_skills:
        weaknesses.append(f"未明确体现技能：{'、'.join(missing_skills)}")
    if not candidate.internship_experience:
        weaknesses.append("未明确体现企业实习经历")
    level = "强烈推荐" if score >= 85 else "推荐" if score >= 70 else "潜力候选" if score >= 55 else "谨慎考虑"
    return Recommendation(
        candidate=candidate,
        score=score,
        recommendation_level=level,
        reasons=reasons[:3] or ["候选人整体背景与岗位需求具有一定相关性"],
        evidence=candidate.evidence[:2],
        weaknesses=weaknesses[:2] or ["暂未发现显著短板"],
        breakdown=breakdown,
        retrieval_score=round(retrieval_score, 4),
    )


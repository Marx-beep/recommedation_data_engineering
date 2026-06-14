import asyncio

from src.extraction.job_parser import parse_job_locally
from src.models import RecommendationRequest
from src.service import recommend


def test_local_job_parser_extracts_domain_terms():
    profile = parse_job_locally("招聘固态电解质博士，熟悉 XRD、SEM 和电化学测试，面向新能源研发")
    assert profile.degree_requirement == "博士"
    assert "固态电解质" in profile.research_directions
    assert "XRD" in profile.required_skills
    assert profile.industry_direction == "新能源"


def test_pipeline_returns_ranked_candidates():
    response = asyncio.run(
        recommend(
            RecommendationRequest(
                query="招聘固态电解质博士，熟悉 XRD、SEM 和电化学测试",
                top_k=3,
                use_llm=False,
            )
        )
    )
    assert len(response.recommendations) == 3
    assert response.recommendations[0].candidate.resume_id in {"R001", "R008"}
    assert response.recommendations[0].rank == 1
    assert response.recommendations[0].score >= response.recommendations[1].score


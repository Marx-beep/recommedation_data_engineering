import asyncio

from src.extraction.job_parser import parse_job_locally
from src.ingestion.resume_parser import _merge_model_candidate, parse_resume_locally
from src.ingestion.text_extractor import clean_and_anonymize
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


def test_resume_import_parser_structures_and_anonymizes_text():
    text = """张三 13812345678 zhang@example.com
    清华大学 材料科学与工程专业 博士 2026
    研究方向：固态电解质与锂离子电池
    熟悉 XRD、SEM、电化学测试，发表 SCI 论文 3 篇。
    项目：氧化物固态电解质界面稳定性研究。"""
    cleaned = clean_and_anonymize(text)
    candidate = parse_resume_locally(cleaned, "ITEST00001")
    assert "13812345678" not in cleaned
    assert "zhang@example.com" not in cleaned
    assert candidate.degree == "博士"
    assert "固态电解质" in candidate.research_directions
    assert "XRD" in candidate.experimental_skills


def test_partial_llm_resume_result_merges_with_local_profile():
    fallback = parse_resume_locally("清华大学 材料科学与工程专业 博士 2026 XRD 固态电解质", "ITEST00002")
    candidate = _merge_model_candidate(
        {"degree": None, "experimental_skills": ["SEM"], "evidence": {"skill": "SEM"}},
        fallback,
        "ITEST00002",
    )
    assert candidate.degree == "博士"
    assert set(candidate.experimental_skills) == {"XRD", "SEM"}
    assert candidate.school == "清华大学"


def test_complete_resume_sections_are_structured():
    text = """清华大学 材料科学与工程专业 博士 2026
    GPA 3.8/4.0，专业排名前 10%
    研究方向：固态电解质与锂离子电池
    科研项目：负责氧化物固态电解质界面稳定性研究，发表 SCI 论文 3 篇。
    英语 CET-6 580 分
    全国大学生材料设计竞赛一等奖
    企业实习：动力电池研发部门实习
    获得 Python 技能认证
    担任学生会部长
    自我评价：学习能力强，具备团队协作能力"""
    candidate = parse_resume_locally(text, "ITEST00003")
    assert "前 10%" in candidate.gpa_ranking
    assert candidate.research_experience
    assert candidate.research_experience[0].paper_outputs
    assert "CET-6" in candidate.english_level
    assert candidate.competition_awards
    assert candidate.work_experience
    assert candidate.skill_certifications
    assert candidate.student_work
    assert "团队协作" in candidate.self_evaluation

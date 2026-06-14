from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResearchExperience(BaseModel):
    title: str = ""
    summary: str = ""
    paper_outputs: list[str] = Field(default_factory=list)
    content_tags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class CareerExperience(BaseModel):
    organization: str = ""
    role: str = ""
    period: str = ""
    summary: str = ""
    content_tags: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    resume_id: str
    degree: Literal["本科", "硕士", "博士"]
    school: str
    major: str
    graduation_year: int
    research_directions: list[str]
    experimental_skills: list[str]
    software_skills: list[str]
    paper_count: int
    patent_count: int = 0
    project_experience: str
    internship_experience: str = ""
    industry_tags: list[str]
    evidence: list[str]
    gpa_ranking: str = ""
    research_experience: list[ResearchExperience] = Field(default_factory=list)
    english_level: str = ""
    competition_awards: list[str] = Field(default_factory=list)
    work_experience: list[CareerExperience] = Field(default_factory=list)
    skill_certifications: list[str] = Field(default_factory=list)
    student_work: list[str] = Field(default_factory=list)
    self_evaluation: str = ""
    resume_summary: str = ""


class JobProfile(BaseModel):
    degree_requirement: str = "硕士"
    research_directions: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_outputs: list[str] = Field(default_factory=list)
    industry_direction: str = ""


class RecommendationRequest(BaseModel):
    query: str = Field(min_length=4, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)
    strict_degree: bool = True
    use_llm: bool = True


class ScoreBreakdown(BaseModel):
    research: int
    skills: int
    education: int
    outputs: int
    industry: int


class Recommendation(BaseModel):
    rank: int = 0
    candidate: Candidate
    score: int
    recommendation_level: str
    reasons: list[str]
    evidence: list[str]
    weaknesses: list[str]
    breakdown: ScoreBreakdown
    retrieval_score: float


class RecommendationResponse(BaseModel):
    job_profile: JobProfile
    recommendations: list[Recommendation]
    pipeline: list[dict]
    llm_used: bool
    model: str
    elapsed_ms: int

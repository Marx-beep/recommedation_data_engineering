from __future__ import annotations

from time import perf_counter

from src.config import settings
from src.data_loader import load_candidates
from src.extraction.job_parser import parse_job
from src.models import RecommendationRequest, RecommendationResponse
from src.ranking.llm_ranker import llm_adjust
from src.ranking.reranker import rerank
from src.ranking.rule_filter import apply_hard_filters
from src.ranking.scorer import score_candidate
from src.retrieval.retriever import retrieve


async def recommend(request: RecommendationRequest) -> RecommendationResponse:
    started = perf_counter()
    profile, parse_llm_used = await parse_job(request.query, request.use_llm)
    candidates = load_candidates()
    recalled = retrieve(profile, candidates, top_n=min(12, max(request.top_k * 2, 8)))
    filtered = apply_hard_filters(recalled, profile, request.strict_degree)
    scored = [score_candidate(candidate, profile, similarity) for candidate, similarity in filtered]
    rank_llm_used = await llm_adjust(request.query, scored, request.use_llm)
    results = rerank(scored, request.top_k)
    pipeline = [
        {"name": "需求解析", "detail": f"提取 {len(profile.research_directions)} 个方向、{len(profile.required_skills)} 项技能", "count": 1},
        {"name": "RAG 召回", "detail": "轻量语义向量召回候选人", "count": len(recalled)},
        {"name": "硬条件过滤", "detail": "学历与业务规则过滤", "count": len(filtered)},
        {"name": "精排与重排", "detail": "五维评分、LLM 校准与多样性重排", "count": len(results)},
    ]
    return RecommendationResponse(
        job_profile=profile,
        recommendations=results,
        pipeline=pipeline,
        llm_used=parse_llm_used or rank_llm_used,
        model=settings.model,
        elapsed_ms=round((perf_counter() - started) * 1000),
    )


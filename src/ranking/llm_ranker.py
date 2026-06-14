from __future__ import annotations

import json
import re

import httpx

from src.config import settings
from src.extraction.prompts import ranking_prompt
from src.models import Recommendation


async def llm_adjust(query: str, recommendations: list[Recommendation], enabled: bool) -> bool:
    if not enabled or not settings.use_llm or not settings.api_key or not recommendations:
        return False
    profiles = [
        {
            "resume_id": item.candidate.resume_id,
            "initial_score": item.score,
            "research": item.candidate.research_directions,
            "skills": item.candidate.experimental_skills + item.candidate.software_skills,
            "papers": item.candidate.paper_count,
            "project": item.candidate.project_experience,
            "internship": item.candidate.internship_experience,
            "gpa_ranking": item.candidate.gpa_ranking,
            "english_level": item.candidate.english_level,
            "awards": item.candidate.competition_awards,
            "certifications": item.candidate.skill_certifications,
            "summary": item.candidate.resume_summary,
        }
        for item in recommendations[:8]
    ]
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                f"{settings.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json={
                    "model": settings.model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": ranking_prompt(query, profiles)}],
                },
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            data = json.loads(text[text.find("{") : text.rfind("}") + 1])
            adjustments = {item["resume_id"]: item for item in data.get("items", [])}
            for recommendation in recommendations:
                adjustment = adjustments.get(recommendation.candidate.resume_id, {})
                delta = max(-5, min(5, int(adjustment.get("score_adjustment", 0))))
                recommendation.score = max(0, min(100, recommendation.score + delta))
                if adjustment.get("summary"):
                    recommendation.reasons.insert(0, str(adjustment["summary"])[:100])
            return True
    except (httpx.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return False

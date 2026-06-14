from __future__ import annotations

import json
import re

import httpx

from src.config import settings
from src.extraction.prompts import JOB_PARSE_SYSTEM
from src.features.tag_schema import EXPERIMENTAL_SKILLS, INDUSTRY_TAGS, RESEARCH_DIRECTIONS, SOFTWARE_SKILLS
from src.models import JobProfile


ALIASES = {
    "锂电": "锂离子电池",
    "锂电池": "锂离子电池",
    "钠电": "钠离子电池",
    "固态电池": "固态电解质",
    "电化学": "电化学测试",
    "三元正极": "正极材料",
    "电池研发": "新能源",
}


def parse_job_locally(query: str) -> JobProfile:
    normalized = query
    for alias, canonical in ALIASES.items():
        if alias in normalized:
            normalized += f" {canonical}"

    degree = "博士" if "博士" in normalized else "硕士" if "硕士" in normalized else "本科"
    directions = [tag for tag in RESEARCH_DIRECTIONS if tag in normalized]
    skills = [tag for tag in EXPERIMENTAL_SKILLS + SOFTWARE_SKILLS if tag.lower() in normalized.lower()]
    outputs = [tag for tag in ["SCI论文", "专利", "项目经验", "企业实习"] if tag.replace("论文", "") in normalized]
    industry = next((tag for tag in INDUSTRY_TAGS if tag in normalized), "")
    return JobProfile(
        degree_requirement=degree,
        research_directions=list(dict.fromkeys(directions)),
        required_skills=list(dict.fromkeys(skills)),
        preferred_outputs=outputs,
        industry_direction=industry,
    )


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("No JSON object in model response")
    return json.loads(text[start : end + 1])


async def parse_job(query: str, use_llm: bool = True) -> tuple[JobProfile, bool]:
    fallback = parse_job_locally(query)
    if not use_llm or not settings.use_llm or not settings.api_key:
        return fallback, False

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{settings.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json={
                    "model": settings.model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": JOB_PARSE_SYSTEM},
                        {"role": "user", "content": query},
                    ],
                },
            )
            response.raise_for_status()
            parsed = JobProfile.model_validate(_extract_json(response.json()["choices"][0]["message"]["content"]))
            parsed.degree_requirement = parsed.degree_requirement or fallback.degree_requirement
            parsed.research_directions = list(dict.fromkeys(fallback.research_directions + parsed.research_directions))
            parsed.required_skills = list(dict.fromkeys(fallback.required_skills + parsed.required_skills))
            parsed.preferred_outputs = list(dict.fromkeys(fallback.preferred_outputs + parsed.preferred_outputs))
            parsed.industry_direction = parsed.industry_direction or fallback.industry_direction
            return parsed, True
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        return fallback, False

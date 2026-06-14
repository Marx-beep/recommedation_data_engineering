from __future__ import annotations

import json
import re
from datetime import datetime

import httpx

from src.config import settings
from src.features.tag_schema import EXPERIMENTAL_SKILLS, INDUSTRY_TAGS, RESEARCH_DIRECTIONS, SOFTWARE_SKILLS
from src.models import Candidate


RESUME_SYSTEM_PROMPT = """你是材料化学研发招聘场景的简历结构化解析器。
根据匿名简历文本提取候选人画像，只输出 JSON，不要 markdown。
字段：degree、school、major、graduation_year、research_directions、experimental_skills、
software_skills、paper_count、patent_count、project_experience、internship_experience、
industry_tags、evidence。degree 只能是本科、硕士、博士。evidence 必须来自原文，不得编造。"""


def _matches(text: str, options: list[str]) -> list[str]:
    return [item for item in options if item.lower() in text.lower()]


def parse_resume_locally(text: str, resume_id: str) -> Candidate:
    degree = "博士" if "博士" in text else "硕士" if "硕士" in text else "本科"
    school_match = re.search(r"([\u4e00-\u9fff]{2,20}(?:大学|学院|研究所))", text)
    major_match = re.search(r"(?:专业|主修|研究方向)[：:\s]*([\u4e00-\u9fff]{2,20})", text)
    years = [int(value) for value in re.findall(r"20(?:2[4-9]|3\d)", text)]
    paper_matches = re.findall(r"(?:SCI|论文)[^\d]{0,8}(\d+)", text, re.IGNORECASE)
    patent_matches = re.findall(r"专利[^\d]{0,8}(\d+)", text)
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 12]
    directions = _matches(text, RESEARCH_DIRECTIONS)
    skills = _matches(text, EXPERIMENTAL_SKILLS)
    software = _matches(text, SOFTWARE_SKILLS)
    industries = _matches(text, INDUSTRY_TAGS)
    return Candidate(
        resume_id=resume_id,
        degree=degree,
        school=school_match.group(1) if school_match else "未识别院校",
        major=major_match.group(1)[:20] if major_match else "材料相关专业",
        graduation_year=max(years) if years else datetime.now().year,
        research_directions=directions or ["材料研发"],
        experimental_skills=skills,
        software_skills=software,
        paper_count=max([int(value) for value in paper_matches], default=text.lower().count("sci")),
        patent_count=max([int(value) for value in patent_matches], default=0),
        project_experience=next((line for line in lines if "项目" in line or "课题" in line), lines[0] if lines else "未识别"),
        internship_experience=next((line for line in lines if "实习" in line or "企业" in line), ""),
        industry_tags=industries,
        evidence=lines[:3] or [text[:160]],
    )


async def parse_resume(text: str, resume_id: str, use_llm: bool) -> tuple[Candidate, bool]:
    fallback = parse_resume_locally(text, resume_id)
    if not use_llm or not settings.use_llm or not settings.api_key:
        return fallback, False
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(
                f"{settings.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json={
                    "model": settings.model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": RESUME_SYSTEM_PROMPT},
                        {"role": "user", "content": text[:24000]},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            try:
                parsed = json.loads(content[content.find("{") : content.rfind("}") + 1])
                return _merge_model_candidate(parsed, fallback, resume_id), True
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                return fallback, True
    except (httpx.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return fallback, False


def _merge_model_candidate(parsed: dict, fallback: Candidate, resume_id: str) -> Candidate:
    fallback_data = fallback.model_dump()
    parsed["resume_id"] = resume_id
    for field in ["degree", "school", "major", "graduation_year", "paper_count", "patent_count", "project_experience", "internship_experience"]:
        if parsed.get(field) is None or parsed.get(field) == "":
            parsed[field] = fallback_data[field]
    if parsed["degree"] not in {"本科", "硕士", "博士"}:
        parsed["degree"] = fallback.degree
    parsed["graduation_year"] = int(parsed["graduation_year"])
    parsed["paper_count"] = int(parsed["paper_count"])
    parsed["patent_count"] = int(parsed["patent_count"])
    for field in ["research_directions", "experimental_skills", "software_skills", "industry_tags"]:
        model_values = parsed.get(field) if isinstance(parsed.get(field), list) else []
        parsed[field] = list(dict.fromkeys(fallback_data[field] + model_values))
    evidence = parsed.get("evidence")
    if isinstance(evidence, str):
        parsed["evidence"] = [evidence]
    elif not isinstance(evidence, list) or not evidence:
        parsed["evidence"] = fallback.evidence
    return Candidate.model_validate(parsed)

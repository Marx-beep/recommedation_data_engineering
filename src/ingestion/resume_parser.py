from __future__ import annotations

import json
import re
from datetime import datetime

import httpx

from src.config import settings
from src.features.tag_schema import EXPERIMENTAL_SKILLS, INDUSTRY_TAGS, RESEARCH_DIRECTIONS, SOFTWARE_SKILLS
from src.models import Candidate, CareerExperience, ResearchExperience


RESUME_SYSTEM_PROMPT = """你是严谨的简历结构化解析与概括助手。完整阅读匿名简历，将信息归入指定字段并概括。
只输出 JSON，不要 markdown，不得编造原文没有的信息。无法识别时使用空字符串或空数组。

必须输出以下结构：
{
  "degree": "本科|硕士|博士",
  "school": "学校",
  "major": "专业",
  "graduation_year": 2026,
  "gpa_ranking": "绩点、成绩或排名的原文概括",
  "research_directions": ["研究方向标签"],
  "research_experience": [{
    "title": "科研项目或课题名称",
    "summary": "研究内容、本人贡献和方法的简洁概括",
    "paper_outputs": ["论文发表、专利或科研成果"],
    "content_tags": ["研究内容标签"],
    "evidence": ["支持该概括的原文片段"]
  }],
  "english_level": "英语考试、分数及使用能力概括",
  "competition_awards": ["竞赛与获奖概括"],
  "work_experience": [{
    "organization": "实习或工作单位",
    "role": "岗位",
    "period": "时间",
    "summary": "职责与成果概括",
    "content_tags": ["内容标签"]
  }],
  "experimental_skills": ["实验技能"],
  "software_skills": ["软件与计算技能"],
  "skill_certifications": ["技能证书与职业认证"],
  "student_work": ["学生工作与组织经历概括"],
  "self_evaluation": "兜底口袋：不能归入上述字段的能力、特点、兴趣及其他有效信息概括",
  "resume_summary": "候选人整体画像的一段话概括",
  "paper_count": 0,
  "patent_count": 0,
  "project_experience": "最相关科研经历概括",
  "internship_experience": "最相关实习或工作经历概括",
  "industry_tags": ["产业标签"],
  "evidence": ["关键原文证据"]
}

注意：科研经历必须包含论文成果及内容标签；实习和工作统一放入 work_experience；
自我评价是兜底口袋，只有不能归入其他字段的信息才放入其中。"""


def _matches(text: str, options: list[str]) -> list[str]:
    return [item for item in options if item.lower() in text.lower()]


def parse_resume_locally(text: str, resume_id: str) -> Candidate:
    degree = "博士" if "博士" in text else "硕士" if "硕士" in text else "本科"
    school_match = re.search(r"([\u4e00-\u9fff]{2,20}(?:大学|学院|研究所))", text)
    major_match = re.search(r"([\u4e00-\u9fff]{2,20})(?:专业|主修)", text)
    if not major_match:
        major_match = re.search(r"(?:专业|主修)[：:\s]*([\u4e00-\u9fff]{2,20})", text)
    years = [int(value) for value in re.findall(r"20(?:2[4-9]|3\d)", text)]
    paper_matches = re.findall(r"(?:SCI|论文)[^\d]{0,8}(\d+)", text, re.IGNORECASE)
    patent_matches = re.findall(r"专利[^\d]{0,8}(\d+)", text)
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 4]
    directions = _matches(text, RESEARCH_DIRECTIONS)
    skills = _matches(text, EXPERIMENTAL_SKILLS)
    software = _matches(text, SOFTWARE_SKILLS)
    industries = _matches(text, INDUSTRY_TAGS)
    gpa_line = next((line for line in lines if any(key in line.upper() for key in ["GPA", "绩点", "排名", "专业前", "成绩"])), "")
    english_line = next((line for line in lines if any(key in line.upper() for key in ["CET", "IELTS", "TOEFL", "英语", "雅思", "托福"])), "")
    award_lines = [line for line in lines if any(key in line for key in ["竞赛", "获奖", "一等奖", "二等奖", "三等奖", "奖学金"])]
    certification_lines = [line for line in lines if any(key in line for key in ["证书", "认证", "资格证"])]
    student_lines = [line for line in lines if any(key in line for key in ["学生会", "班长", "团支书", "社团", "学生工作"])]
    self_lines = [line for line in lines if any(key in line for key in ["自我评价", "个人评价", "个人优势", "兴趣爱好"])]
    research_lines = [line for line in lines if any(key in line for key in ["项目", "课题", "论文", "科研", "研究"])]
    work_lines = [line for line in lines if any(key in line for key in ["实习", "工作", "公司", "企业"])]
    research_summary = research_lines[0] if research_lines else ""
    work_summary = work_lines[0] if work_lines else ""
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
        internship_experience=work_summary,
        industry_tags=industries,
        evidence=lines[:3] or [text[:160]],
        gpa_ranking=gpa_line,
        research_experience=[ResearchExperience(
            title="科研经历",
            summary=research_summary,
            paper_outputs=[line for line in research_lines if "论文" in line or "SCI" in line or "专利" in line],
            content_tags=list(dict.fromkeys(directions + skills))[:8],
            evidence=research_lines[:3],
        )] if research_lines else [],
        english_level=english_line,
        competition_awards=award_lines,
        work_experience=[CareerExperience(
            organization="未识别单位",
            summary=work_summary,
            content_tags=industries,
        )] if work_summary else [],
        skill_certifications=certification_lines,
        student_work=student_lines,
        self_evaluation="；".join(self_lines),
        resume_summary=f"{degree}，研究方向包括{'、'.join(directions or ['材料研发'])}，核心技能包括{'、'.join((skills + software)[:6]) or '待补充'}。",
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
    for field in [
        "degree", "school", "major", "graduation_year", "paper_count", "patent_count",
        "project_experience", "internship_experience", "gpa_ranking", "english_level",
        "self_evaluation", "resume_summary",
    ]:
        if parsed.get(field) is None or parsed.get(field) == "":
            parsed[field] = fallback_data[field]
    if parsed["degree"] not in {"本科", "硕士", "博士"}:
        parsed["degree"] = fallback.degree
    parsed["graduation_year"] = int(parsed["graduation_year"])
    parsed["paper_count"] = int(parsed["paper_count"])
    parsed["patent_count"] = int(parsed["patent_count"])
    for field in [
        "research_directions", "experimental_skills", "software_skills", "industry_tags",
        "competition_awards", "skill_certifications", "student_work",
    ]:
        model_values = parsed.get(field) if isinstance(parsed.get(field), list) else []
        parsed[field] = list(dict.fromkeys(fallback_data[field] + model_values))
    evidence = parsed.get("evidence")
    if isinstance(evidence, str):
        parsed["evidence"] = [evidence]
    elif not isinstance(evidence, list) or not evidence:
        parsed["evidence"] = fallback.evidence
    for field in ["research_experience", "work_experience"]:
        if not isinstance(parsed.get(field), list):
            parsed[field] = fallback_data[field]
    return Candidate.model_validate(parsed)

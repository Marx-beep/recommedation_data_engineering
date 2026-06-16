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
优先抽取有证据的信息，忽略页眉页脚、联系方式占位、求职网站水印、重复目录、空白符、乱码和排版碎片。
不要把同一条信息重复塞进多个字段；自我评价只能放无法归入学校、专业、科研、英语、竞赛、实习、技能认证、学生工作的内容。
每个列表字段最多输出 8 条，每条尽量不超过 80 个中文字符；证据片段必须来自原文且不超过 120 个中文字符。

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

NOISE_MARKERS = [
    "简历", "个人简历", "求职意向", "联系电话", "手机", "邮箱", "email", "e-mail",
    "微信", "地址", "出生年月", "籍贯", "政治面貌", "证件照", "照片", "页码",
    "智联招聘", "前程无忧", "猎聘", "BOSS直聘", "请勿外传", "保密", "confidential",
]
SELF_EVALUATION_BLOCKERS = [
    "GPA", "绩点", "排名", "CET", "IELTS", "TOEFL", "英语", "雅思", "托福",
    "论文", "SCI", "专利", "项目", "课题", "科研", "研究", "实习", "工作",
    "公司", "企业", "竞赛", "获奖", "证书", "认证", "学生会", "班长", "团支书",
]


def _matches(text: str, options: list[str]) -> list[str]:
    return [item for item in options if item.lower() in text.lower()]


def _compact(value: str, limit: int = 120) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n:：；;,，。|")
    value = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", value)
    return value[:limit]


def _is_noise(value: str) -> bool:
    text = _compact(value, 220)
    if len(text) < 2:
        return True
    if len(re.sub(r"[\W_]+", "", text)) < 2:
        return True
    ascii_ratio = sum(ch.isascii() for ch in text) / max(len(text), 1)
    if ascii_ratio > 0.85 and not re.search(r"(GPA|CET|IELTS|TOEFL|SCI|XRD|SEM|TEM|XPS|Python|Matlab)", text, re.I):
        return True
    return any(marker.lower() in text.lower() for marker in NOISE_MARKERS)


def _clean_list(values: object, *, limit: int = 8, item_limit: int = 100) -> list[str]:
    if isinstance(values, str):
        values = re.split(r"[；;。\n]+", values)
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = " ".join(str(v) for v in value.values() if isinstance(v, (str, int, float)))
        item = _compact(str(value), item_limit)
        if item and not _is_noise(item) and item not in cleaned:
            cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned


def _first_signal_line(lines: list[str], keywords: list[str]) -> str:
    return next((line for line in lines if any(key in line.upper() for key in keywords)), "")


def _safe_int(value: object, default: int) -> int:
    try:
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            return int(match.group()) if match else default
        return int(value)
    except (TypeError, ValueError):
        return default


def _prepare_resume_text(text: str) -> str:
    lines = []
    seen = set()
    for raw_line in text.splitlines():
        line = _compact(raw_line, 220)
        if _is_noise(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines)


def parse_resume_locally(text: str, resume_id: str) -> Candidate:
    text = _prepare_resume_text(text)
    degree = "博士" if "博士" in text else "硕士" if "硕士" in text else "本科"
    school_match = re.search(r"([\u4e00-\u9fff]{2,20}(?:大学|学院|研究所))", text)
    major_match = re.search(r"([\u4e00-\u9fff]{2,20})(?:专业|主修)", text)
    if not major_match:
        major_match = re.search(r"(?:专业|主修)[：:\s]*([\u4e00-\u9fff]{2,20})", text)
    years = [int(value) for value in re.findall(r"20(?:2[4-9]|3\d)", text)]
    paper_matches = re.findall(r"(?:SCI|论文)[^\d]{0,8}(\d+)", text, re.IGNORECASE)
    patent_matches = re.findall(r"专利[^\d]{0,8}(\d+)", text)
    lines = [_compact(line) for line in text.splitlines() if not _is_noise(line)]
    directions = _matches(text, RESEARCH_DIRECTIONS)
    skills = _matches(text, EXPERIMENTAL_SKILLS)
    software = _matches(text, SOFTWARE_SKILLS)
    industries = _matches(text, INDUSTRY_TAGS)
    gpa_line = _first_signal_line(lines, ["GPA", "绩点", "排名", "专业前", "成绩"])
    english_line = _first_signal_line(lines, ["CET", "IELTS", "TOEFL", "英语", "雅思", "托福"])
    award_lines = _clean_list([line for line in lines if any(key in line for key in ["竞赛", "获奖", "一等奖", "二等奖", "三等奖", "奖学金"])])
    certification_lines = _clean_list([line for line in lines if any(key in line for key in ["证书", "认证", "资格证"])])
    student_lines = _clean_list([line for line in lines if any(key in line for key in ["学生会", "班长", "团支书", "社团", "学生工作"])])
    self_lines = _clean_list([
        line for line in lines
        if any(key in line for key in ["自我评价", "个人评价", "个人优势", "兴趣爱好"])
        and not any(key in line.upper() for key in SELF_EVALUATION_BLOCKERS)
    ], limit=4)
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
        evidence=_clean_list(lines, limit=3, item_limit=120) or [text[:160]],
        gpa_ranking=_compact(gpa_line, 80),
        research_experience=[ResearchExperience(
            title="科研经历",
            summary=_compact(research_summary, 140),
            paper_outputs=_clean_list([line for line in research_lines if "论文" in line or "SCI" in line or "专利" in line], limit=6),
            content_tags=list(dict.fromkeys(directions + skills))[:8],
            evidence=_clean_list(research_lines, limit=3),
        )] if research_lines else [],
        english_level=_compact(english_line, 80),
        competition_awards=award_lines,
        work_experience=[CareerExperience(
            organization="未识别单位",
            summary=_compact(work_summary, 140),
            content_tags=industries,
        )] if work_summary else [],
        skill_certifications=certification_lines,
        student_work=student_lines,
        self_evaluation="；".join(self_lines),
        resume_summary=f"{degree}，研究方向包括{'、'.join(directions or ['材料研发'])}，核心技能包括{'、'.join((skills + software)[:6]) or '待补充'}。",
    )


async def parse_resume(text: str, resume_id: str, use_llm: bool) -> tuple[Candidate, bool]:
    cleaned_text = _prepare_resume_text(text)
    fallback = parse_resume_locally(cleaned_text, resume_id)
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
                        {"role": "user", "content": cleaned_text[:24000]},
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
    parsed = parsed if isinstance(parsed, dict) else {}
    fallback_data = fallback.model_dump()
    parsed["resume_id"] = resume_id
    for field in [
        "degree", "school", "major", "graduation_year", "paper_count", "patent_count",
        "project_experience", "internship_experience", "gpa_ranking", "english_level",
        "self_evaluation", "resume_summary",
    ]:
        if isinstance(parsed.get(field), str):
            parsed[field] = _compact(parsed[field], 180)
        if parsed.get(field) is None or parsed.get(field) == "" or _is_noise(str(parsed.get(field))):
            parsed[field] = fallback_data[field]
    if parsed["degree"] not in {"本科", "硕士", "博士"}:
        parsed["degree"] = fallback.degree
    parsed["graduation_year"] = _safe_int(parsed.get("graduation_year"), fallback.graduation_year)
    parsed["paper_count"] = _safe_int(parsed.get("paper_count"), fallback.paper_count)
    parsed["patent_count"] = _safe_int(parsed.get("patent_count"), fallback.patent_count)
    for field in [
        "research_directions", "experimental_skills", "software_skills", "industry_tags",
        "competition_awards", "skill_certifications", "student_work",
    ]:
        model_values = _clean_list(parsed.get(field), limit=8)
        parsed[field] = list(dict.fromkeys(fallback_data[field] + model_values))
    evidence = parsed.get("evidence")
    cleaned_evidence = _clean_list(evidence, limit=6, item_limit=120)
    if cleaned_evidence:
        parsed["evidence"] = cleaned_evidence
    else:
        parsed["evidence"] = fallback.evidence
    parsed["research_experience"] = _clean_research_records(parsed.get("research_experience")) or fallback_data["research_experience"]
    parsed["work_experience"] = _clean_work_records(parsed.get("work_experience")) or fallback_data["work_experience"]
    if any(key in parsed.get("self_evaluation", "").upper() for key in SELF_EVALUATION_BLOCKERS):
        parsed["self_evaluation"] = fallback.self_evaluation
    return Candidate.model_validate(parsed)


def _clean_research_records(records: object) -> list[dict]:
    if not isinstance(records, list):
        return []
    cleaned = []
    for record in records[:6]:
        if not isinstance(record, dict):
            continue
        item = {
            "title": _compact(record.get("title", ""), 80) or "科研经历",
            "summary": _compact(record.get("summary", ""), 160),
            "paper_outputs": _clean_list(record.get("paper_outputs"), limit=6),
            "content_tags": _clean_list(record.get("content_tags"), limit=8, item_limit=30),
            "evidence": _clean_list(record.get("evidence"), limit=3, item_limit=120),
        }
        if item["summary"] or item["paper_outputs"] or item["content_tags"]:
            cleaned.append(item)
    return cleaned


def _clean_work_records(records: object) -> list[dict]:
    if not isinstance(records, list):
        return []
    cleaned = []
    for record in records[:8]:
        if not isinstance(record, dict):
            continue
        item = {
            "organization": _compact(record.get("organization", ""), 60),
            "role": _compact(record.get("role", ""), 60),
            "period": _compact(record.get("period", ""), 40),
            "summary": _compact(record.get("summary", ""), 160),
            "content_tags": _clean_list(record.get("content_tags"), limit=6, item_limit=30),
        }
        if item["summary"] or item["organization"] or item["role"]:
            cleaned.append(item)
    return cleaned

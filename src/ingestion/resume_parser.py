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
你的首要目标是覆盖完整简历信息：逐行阅读原文，理解词语、句子和段落在具体上下文中的含义，把每一条有效信息归入最合适模块。
不要只抽关键词；要按语义判断，例如同一句里可能同时包含教育、绩点、专业、研究方向或技能信息。
除联系方式脱敏占位、水印、纯页码、重复空标题外，所有简历信息都必须进入某个结构化字段；无法归入固定模块的内容放入 other_information，并在 source_coverage 说明归档情况。
自我评价只放能力、性格、兴趣、个人特点等信息；其他无法归类但仍有价值的信息放 other_information。
列表字段可以输出多条，优先完整保留，不要为了简短而丢失论文、奖项、项目、学生工作、技能或实习条目。
遇到 OCR 文本时要识别常见变体：RE/荣誉/奖学金归入竞赛获奖；研究成果/SCI/IF/一作/专利归入科研经历的 paper_outputs；
校园经历/社团/党支部/班委/学生会/俱乐部归入学生工作；企业/公司/有限公司/实习/测试分析员等归入实习或工作；
软件、普通话、职业资格、证书归入技能认证；GPA、绩点、分数、排名必须归入 gpa_ranking。

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
  "other_information": ["不能放入上述模块但仍应保留的其他简历信息"],
  "source_coverage": ["覆盖检查：说明哪些原文板块已归入哪些字段，是否存在难以判断的信息"],
  "resume_summary": "候选人整体画像的一段话概括",
  "paper_count": 0,
  "patent_count": 0,
  "project_experience": "最相关科研经历概括",
  "internship_experience": "最相关实习或工作经历概括",
  "industry_tags": ["产业标签"],
  "evidence": ["关键原文证据"]
}

注意：科研经历必须包含论文成果及内容标签；实习和工作统一放入 work_experience；
同一原文信息不要重复进入多个模块，但必须至少进入一个模块或 other_information。"""

NOISE_MARKERS = [
    "联系电话", "手机", "邮箱", "email", "e-mail",
    "微信", "证件照", "照片", "页码",
    "智联招聘", "前程无忧", "猎聘", "BOSS直聘", "请勿外传", "保密", "confidential",
]
SELF_EVALUATION_BLOCKERS = [
    "GPA", "绩点", "排名", "CET", "IELTS", "TOEFL", "英语", "雅思", "托福",
    "论文", "SCI", "专利", "项目", "课题", "科研", "研究", "实习", "工作",
    "公司", "企业", "竞赛", "获奖", "证书", "认证", "学生会", "班长", "团支书",
]
DEGREE_ALIASES = {"博士": "博士", "硕士": "硕士", "研究生": "硕士", "学士": "本科", "本科": "本科"}
HONOR_KEYS = ["RE:", "荣誉", "奖励", "奖学金", "三好学生", "优秀", "先进个人", "标兵", "竞赛", "获奖", "一等奖", "二等奖", "三等奖"]
STUDENT_WORK_KEYS = ["校园经历", "学生会", "社团", "社长", "部长", "班长", "班级", "委员", "团支书", "党支部", "俱乐部", "方阵", "干事"]
WORK_KEYS = ["实习", "工作经历", "有限公司", "公司", "企业", "科技园", "研究院", "工程师", "测试分析员", "研发部"]
SKILL_CERT_KEYS = ["证书", "认证", "资格证", "普通话", "软件", "Office", "Chemdraw", "Origin", "MestReNova", "职业资格"]
SELF_KEYS = ["自我评价", "个人评价", "个人优势", "兴趣爱好", "积极", "上进", "沟通", "耐心", "责任心", "解决问题", "理解能力"]
SECTION_HEADERS = {"简历", "个人简历", "基本信息", "教育表", "教育经历", "项目经历", "科研经历", "研究成果", "校园经历", "实习经历", "工作经历", "技能证书"}


def _matches(text: str, options: list[str]) -> list[str]:
    return [item for item in options if item.lower() in text.lower()]


def _compact(value: str, limit: int = 120) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n:：；;,，。|")
    value = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", value)
    return value[:limit]


def _is_noise(value: str) -> bool:
    text = _compact(value, 220)
    if any(text.startswith(header) and len(text) <= len(header) + 6 for header in SECTION_HEADERS):
        return True
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
        if item and item not in SECTION_HEADERS and not _is_noise(item) and item not in cleaned:
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


def _contains_any(line: str, keys: list[str]) -> bool:
    upper = line.upper()
    return any(key.upper() in upper for key in keys)


def _extract_degree(text: str) -> str:
    for key in ["博士", "硕士", "研究生", "学士", "本科"]:
        if key in text:
            return DEGREE_ALIASES[key]
    return "本科"


def _education_lines(lines: list[str]) -> list[str]:
    return [
        line for line in lines
        if re.search(r"(大学|学院|研究所)", line)
        and not _contains_any(line, ["主修课程", "课程", "平台", "DIEU", "UNIVERSITY OF"])
    ]


def _extract_school(lines: list[str]) -> str:
    for line in _education_lines(lines):
        match = re.search(r"([\u4e00-\u9fff]{2,24}(?:大学|学院|研究所))", line)
        if match:
            return match.group(1)
    return "未识别院校"


def _extract_major(lines: list[str]) -> str:
    for line in _education_lines(lines):
        tail = re.sub(r"^.*?(?:大学|学院|研究所)", "", line)
        tail = re.sub(r"\(?\s*(?:博士|硕士|研究生|学士|本科)[^)]*\)?", " ", tail)
        tail = re.sub(r"20\d{2}[.\-/年]\d{0,2}[-至~—–]*20?\d{0,4}[.\-/年]?\d{0,2}", " ", tail)
        tail = re.sub(r"\d+(?:\.\d+)?/\d+(?:\.\d+)?", " ", tail)
        candidates = [
            _compact(part, 40) for part in re.split(r"[，,;；\s]+", tail)
            if 2 <= len(_compact(part, 40)) <= 30
            and not _contains_any(part, ["双一流", "211", "985", "平台", "导师", "研究方向"])
        ]
        if candidates:
            return candidates[0]
    for line in lines:
        if _contains_any(line, ["主修", "专业"]):
            match = re.search(r"(?:专业|主修)[：:\s]*([\u4e00-\u9fffA-Za-z0-9、/（）()]{2,30})", line)
            if match and not _contains_any(match.group(1), ["课程"]):
                return _compact(match.group(1), 30)
    return "材料相关专业"


def _extract_gpa(lines: list[str]) -> str:
    for line in lines:
        has_fraction_gpa = re.search(r"\d+\.\d+/\d+(?:\.\d+)?|\d+(?:\.\d+)?/4(?:\.0+)?", line)
        if has_fraction_gpa or _contains_any(line, ["GPA", "绩点", "排名", "专业前", "成绩"]):
            return _compact(line, 100)
    return ""


def _paper_output_lines(lines: list[str]) -> list[str]:
    outputs = []
    for line in lines:
        if _contains_any(line, ["SCI", "论文", "专利", "IF", "一作", "通讯", "发表", "在投", "期刊"]):
            outputs.append(line)
    return _clean_list(outputs, limit=40, item_limit=180)


def _research_lines(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        if _contains_any(line, ["研究方向", "科研", "项目", "课题", "博士论文", "研究成果", "设计合成", "制备", "性能研究", "机理", "催化", "材料"]):
            result.append(line)
    return _clean_list(result, limit=40, item_limit=180)


def _work_lines(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        if _contains_any(line, WORK_KEYS) and not _contains_any(line, ["电化学工作站", "测试技术", "主修课程"]):
            result.append(line)
    return _clean_list(result, limit=30, item_limit=180)


MODULE_RULES = {
    "education": ["大学", "学院", "研究所", "博士", "硕士", "本科", "学士", "专业", "主修", "GPA", "绩点", "排名"],
    "research": ["研究方向", "科研", "项目", "课题", "博士论文", "研究成果", "设计", "合成", "制备", "性能", "机理", "材料"],
    "outputs": ["SCI", "论文", "专利", "IF", "一作", "通讯", "发表", "在投", "期刊"],
    "english": ["CET", "IELTS", "TOEFL", "英语", "雅思", "托福"],
    "awards": HONOR_KEYS,
    "work": WORK_KEYS,
    "skills": EXPERIMENTAL_SKILLS + SOFTWARE_SKILLS + SKILL_CERT_KEYS,
    "student_work": STUDENT_WORK_KEYS,
    "self_evaluation": SELF_KEYS,
}


def _source_lines(text: str) -> list[str]:
    prepared = _prepare_resume_text(text)
    return [_compact(line, 260) for line in prepared.splitlines() if not _is_noise(line)]


def _line_modules(line: str) -> list[str]:
    modules = [name for name, keys in MODULE_RULES.items() if _contains_any(line, keys)]
    return modules or ["other_information"]


def _build_llm_resume_input(text: str) -> str:
    lines = _source_lines(text)
    numbered = [f"L{index:03d} [{'/'.join(_line_modules(line))}] {line}" for index, line in enumerate(lines, 1)]
    module_blocks: dict[str, list[str]] = {name: [] for name in [*MODULE_RULES.keys(), "other_information"]}
    for index, line in enumerate(lines, 1):
        for module in _line_modules(line):
            module_blocks[module].append(f"L{index:03d} {line}")
    outline = []
    for module, values in module_blocks.items():
        if values:
            outline.append(f"## {module}\n" + "\n".join(values[:80]))
    return "\n\n".join([
        "请基于下面的完整脱敏简历原文和行级模块草稿做结构化解析。必须覆盖每一条有效行；不能判断模块的放入 other_information。",
        "【完整脱敏原文】",
        text[:60000],
        "【行级模块草稿】",
        "\n".join(numbered[:1000]),
        "【按模块聚合的候选证据】",
        "\n\n".join(outline),
    ])


def _other_information(lines: list[str]) -> list[str]:
    return _clean_list([
        line for line in lines
        if _line_modules(line) == ["other_information"]
    ], limit=60, item_limit=180)


def _coverage_summary(lines: list[str], other: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for line in lines:
        for module in _line_modules(line):
            counts[module] = counts.get(module, 0) + 1
    return [
        f"有效文本行 {len(lines)} 条；已按语义归档到 {len([k for k, v in counts.items() if v])} 类模块",
        "模块行数：" + "；".join(f"{name}={count}" for name, count in sorted(counts.items())),
        f"其他信息兜底 {len(other)} 条",
    ]


def _extract_period(line: str) -> str:
    match = re.search(r"(20\d{2}[.\-/年]\d{0,2}\s*[-至~—–]\s*20?\d{0,4}[.\-/年]?\d{0,2}|20\d{2}[.\-/年]\d{1,2})", line)
    return _compact(match.group(1), 40) if match else ""


def _extract_work_organization(line: str) -> str:
    match = re.search(r"([\u4e00-\u9fffA-Za-z0-9（）()]{2,40}(?:有限公司|公司|企业|科技园|研究院|研究所|中心|实验室|部门))", line)
    return _compact(match.group(1), 60) if match else "未识别单位"


def _extract_work_role(line: str) -> str:
    if "一一" in line:
        line = line.split("一一", 1)[1]
    match = re.search(r"([\u4e00-\u9fffA-Za-z0-9/]{0,12}(?:分析员|工程师|实习生|助理|负责人|经理|研究员|专员|教师))", line)
    return _compact(match.group(1), 40) if match else ""


def parse_resume_locally(text: str, resume_id: str) -> Candidate:
    text = _prepare_resume_text(text)
    lines = [_compact(line) for line in text.splitlines() if not _is_noise(line)]
    degree = _extract_degree(text)
    school = _extract_school(lines)
    major = _extract_major(lines)
    years = [int(value) for value in re.findall(r"20(?:2[4-9]|3\d)", text)]
    paper_matches = re.findall(r"(?:SCI|论文)[^\d]{0,8}(\d+)", text, re.IGNORECASE)
    patent_matches = re.findall(r"专利[^\d]{0,8}(\d+)", text)
    directions = _matches(text, RESEARCH_DIRECTIONS)
    skills = _matches(text, EXPERIMENTAL_SKILLS)
    software = _matches(text, SOFTWARE_SKILLS)
    industries = _matches(text, INDUSTRY_TAGS)
    gpa_line = _extract_gpa(lines)
    english_line = _first_signal_line(lines, ["CET", "IELTS", "TOEFL", "英语", "雅思", "托福"])
    award_lines = _clean_list([line for line in lines if _contains_any(line, HONOR_KEYS)], limit=30, item_limit=180)
    certification_lines = _clean_list([line for line in lines if _contains_any(line, SKILL_CERT_KEYS)], limit=30, item_limit=180)
    student_lines = _clean_list([
        line for line in lines
        if _contains_any(line, STUDENT_WORK_KEYS) and not _contains_any(line, HONOR_KEYS)
    ], limit=30, item_limit=180)
    self_lines = _clean_list([
        line for line in lines
        if _contains_any(line, SELF_KEYS)
        and not any(key in line.upper() for key in SELF_EVALUATION_BLOCKERS)
    ], limit=20, item_limit=180)
    research_lines = _research_lines(lines)
    work_lines = _work_lines(lines)
    paper_outputs = _paper_output_lines(lines)
    other_information = _other_information(lines)
    research_summary = research_lines[0] if research_lines else ""
    work_summary = "；".join(work_lines[:2])
    return Candidate(
        resume_id=resume_id,
        degree=degree,
        school=school,
        major=major,
        graduation_year=max(years) if years else datetime.now().year,
        research_directions=directions or ["材料研发"],
        experimental_skills=skills,
        software_skills=software,
        paper_count=max([int(value) for value in paper_matches], default=text.lower().count("sci")),
        patent_count=max([int(value) for value in patent_matches], default=0),
        project_experience=next((line for line in research_lines if "项目" in line or "课题" in line), research_summary or (lines[0] if lines else "未识别")),
        internship_experience=work_summary,
        industry_tags=industries,
        evidence=_clean_list(lines, limit=12, item_limit=180) or [text[:160]],
        gpa_ranking=_compact(gpa_line, 80),
        research_experience=[ResearchExperience(
            title="科研经历",
            summary=_compact(research_summary, 140),
            paper_outputs=paper_outputs,
            content_tags=list(dict.fromkeys(directions + skills))[:8],
            evidence=_clean_list(research_lines, limit=3),
        )] if research_lines or paper_outputs else [],
        english_level=_compact(english_line, 80),
        competition_awards=award_lines,
        work_experience=[CareerExperience(
            organization=_extract_work_organization(work_summary),
            role=_extract_work_role(work_summary),
            period=_extract_period(work_summary),
            summary=_compact(work_summary, 140),
            content_tags=industries,
        )] if work_summary else [],
        skill_certifications=certification_lines,
        student_work=student_lines,
        self_evaluation="；".join(self_lines),
        resume_summary=f"{degree}，研究方向包括{'、'.join(directions or ['材料研发'])}，核心技能包括{'、'.join((skills + software)[:6]) or '待补充'}。",
        other_information=other_information,
        source_coverage=_coverage_summary(lines, other_information),
    )


async def parse_resume(text: str, resume_id: str, use_llm: bool) -> tuple[Candidate, bool]:
    fallback = parse_resume_locally(text, resume_id)
    if not use_llm or not settings.use_llm or not settings.api_key:
        return fallback, False
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{settings.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json={
                    "model": settings.model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": RESUME_SYSTEM_PROMPT},
                        {"role": "user", "content": _build_llm_resume_input(text)},
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
    scalar_limits = {"self_evaluation": 1600, "resume_summary": 800, "project_experience": 1200, "internship_experience": 1200}
    for field in [
        "degree", "school", "major", "graduation_year", "paper_count", "patent_count",
        "project_experience", "internship_experience", "gpa_ranking", "english_level",
        "self_evaluation", "resume_summary",
    ]:
        if isinstance(parsed.get(field), str):
            parsed[field] = _compact(parsed[field], scalar_limits.get(field, 220))
        if parsed.get(field) is None or parsed.get(field) == "" or _is_noise(str(parsed.get(field))):
            parsed[field] = fallback_data[field]
    if parsed["degree"] not in {"本科", "硕士", "博士"}:
        parsed["degree"] = fallback.degree
    parsed["graduation_year"] = _safe_int(parsed.get("graduation_year"), fallback.graduation_year)
    parsed["paper_count"] = _safe_int(parsed.get("paper_count"), fallback.paper_count)
    parsed["patent_count"] = _safe_int(parsed.get("patent_count"), fallback.patent_count)
    for field in ["research_directions", "experimental_skills", "software_skills", "industry_tags"]:
        model_values = _clean_list(parsed.get(field), limit=60, item_limit=220)
        parsed[field] = list(dict.fromkeys(fallback_data[field] + model_values))
    for field in ["competition_awards", "skill_certifications", "student_work", "other_information", "source_coverage"]:
        model_values = _clean_list(parsed.get(field), limit=60, item_limit=220)
        parsed[field] = model_values or fallback_data[field]
    evidence = parsed.get("evidence")
    cleaned_evidence = _clean_list(evidence, limit=20, item_limit=180)
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
            "paper_outputs": _clean_list(record.get("paper_outputs"), limit=40, item_limit=220),
            "content_tags": _clean_list(record.get("content_tags"), limit=20, item_limit=50),
            "evidence": _clean_list(record.get("evidence"), limit=12, item_limit=180),
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
            "content_tags": _clean_list(record.get("content_tags"), limit=20, item_limit=50),
        }
        if item["summary"] or item["organization"] or item["role"]:
            cleaned.append(item)
    return cleaned

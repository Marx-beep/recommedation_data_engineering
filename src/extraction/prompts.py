JOB_PARSE_SYSTEM = """你是材料化学领域的招聘需求分析器。
请从 HR 的自然语言需求中提取结构化岗位画像，只输出 JSON，不要 markdown。
字段必须包含 degree_requirement、research_directions、required_skills、
preferred_outputs、industry_direction。无法判断的字段使用空字符串或空数组。"""


def ranking_prompt(query: str, profiles: list[dict]) -> str:
    return f"""你是严谨的材料研发招聘顾问。岗位需求如下：
{query}

候选人初排结果如下：
{profiles}

请只输出 JSON 对象，格式为：
{{"items":[{{"resume_id":"R001","score_adjustment":0,"summary":"一句话推荐结论"}}]}}
score_adjustment 必须是 -5 到 5 的整数。不得编造简历中没有的经历。"""


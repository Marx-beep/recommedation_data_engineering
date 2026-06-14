# MaterialMatch HR：材料研发简历智能推荐系统

面向校招与科研型岗位初筛的可运行 Demo。HR 输入自然语言招聘需求，系统自动完成岗位画像解析、候选人召回、规则过滤、五维精排、DeepSeek 校准、多样性重排，并输出带简历证据的 Top-K 推荐结果。

本仓库使用 12 份匿名模拟简历跑通完整链路，不包含真实个人数据。

## 已实现功能

- 原生 HTML/CSS/JavaScript HR 操作台，支持智能推荐、候选人库、流程监控。
- 材料化学领域岗位需求解析，识别学历、研究方向、实验技能、成果与产业方向。
- 轻量语义召回，无需额外部署 FAISS 或 Chroma。
- 学历硬过滤与研究、技能、教育、成果、产业五维评分。
- 调用 `deepseek-v4-flash` 对初排结果进行校准；接口不可用时自动降级到本地规则。
- 展示推荐理由、简历证据、潜在不足和评分拆解。
- 模拟简历涵盖固态电解质、正负极材料、钠离子电池、催化、半导体等方向。
- 候选人库支持 PDF、DOCX、TXT、图片及 ZIP 大批量导入，异步统一结构化解析。

## 快速运行

推荐 Python 3.10 及以上版本。

```powershell
py -m pip install -r requirements.txt
py -m uvicorn src.app:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>。

系统按以下顺序读取 DeepSeek 密钥：

1. 环境变量 `DEEPSEEK_API_KEY`
2. 项目根目录的本地 `api` 文件

`api` 已加入 `.gitignore`，请勿将真实密钥提交到仓库。可用 `.env.example` 作为配置参考。当前模型默认值为 `deepseek-v4-flash`。

## 推荐流程

```text
HR 自然语言需求
  -> 确定性领域标签 + DeepSeek 岗位画像解析
  -> 轻量语义召回 Top-N
  -> 学历硬条件过滤
  -> 五维可解释评分
  -> DeepSeek 精排校准
  -> 多样性业务重排
  -> Top-K 推荐理由 / 证据 / 不足
```

## 目录结构

```text
.
├─ data/structured_resumes/       # 匿名模拟候选人画像
├─ src/
│  ├─ extraction/                 # 岗位需求解析与提示词
│  ├─ features/                   # 材料领域标签体系
│  ├─ ranking/                    # 过滤、评分、LLM 精排、重排
│  ├─ retrieval/                  # 轻量语义召回
│  ├─ app.py                      # FastAPI 服务入口
│  ├─ models.py                   # 数据模型
│  └─ service.py                  # 推荐流程编排
├─ static/                        # HTML/CSS/JavaScript 操作台
├─ tests/                         # 流水线测试
├─ .env.example
└─ requirements.txt
```

## API

- `GET /api/health`：服务、候选人数量和模型配置状态。
- `GET /api/candidates`：结构化匿名候选人列表。
- `POST /api/import-jobs`：流式上传一批简历并创建异步结构化任务。
- `GET /api/import-jobs/{job_id}`：查询批处理进度、成功数与失败原因。
- `POST /api/recommend`：执行完整推荐流程。
- `GET /docs`：FastAPI 自动接口文档。

推荐请求示例：

```json
{
  "query": "招聘固态电解质方向博士，熟悉 XRD、SEM、电化学测试，有 SCI 论文，适合新能源研发岗位",
  "top_k": 5,
  "strict_degree": true,
  "use_llm": true
}
```

## 测试

```powershell
py -m pytest -q
```

## 批量简历导入

候选人库中的“批量导入”支持直接选择大量文件，或上传包含简历的 ZIP。文件先流式写入磁盘，再由后台队列以受控并发执行：

```text
文本抽取 / OCR -> 清洗与隐私脱敏 -> DeepSeek 结构化增强
-> 本地规则降级 -> 单份画像持久化 -> 自动并入候选人库
```

默认限制为每批最多 10,000 份、单文件 50MB、单批总量 5GB，可通过 `.env.example` 中的参数调整。任务状态会持久化，服务重启后自动继续未完成任务。

图片简历 OCR 使用 `pytesseract`，运行机器需额外安装 Tesseract 与中文语言包；未安装时，对应文件会在任务错误列表中给出明确提示，不影响同批其他简历继续处理。

## 隐私与安全

- 示例数据全部为虚构匿名画像。
- 真实简历进入生产环境前应完成姓名、电话、邮箱、地址等字段脱敏。
- 推荐解释必须引用候选人证据，不允许编造经历。
- LLM 调用失败时系统自动使用本地规则完成推荐。

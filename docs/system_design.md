# 系统设计

## 分层职责

| 模块 | 职责 |
| --- | --- |
| `extraction` | 合并确定性领域标签与 DeepSeek 解析结果，构建岗位画像 |
| `retrieval` | 将岗位画像与候选人画像转换为词项和中文二元组，完成余弦召回 |
| `ranking/rule_filter` | 执行学历等硬条件过滤 |
| `ranking/scorer` | 按研究、技能、教育、成果、产业五维生成可解释分数 |
| `ranking/llm_ranker` | 使用 DeepSeek 对初排结果进行有限幅度校准 |
| `ranking/reranker` | 控制方向多样性并输出最终 Top-K |
| `service` | 编排全流程并记录每层候选人数量 |
| `ingestion` | 流式接收批量简历、磁盘任务队列、文本抽取、脱敏与统一结构化 |

## 降级策略

模型未配置、超时或返回异常时，系统继续使用本地解析和评分，不影响基本推荐能力。LLM 调整幅度限制在 `-5` 到 `+5`，避免模型覆盖业务规则。

## 生产化扩展

接入真实简历时可在 `data_loader` 前增加 PDF/OCR、清洗、脱敏和结构化抽取任务；候选人量级上升后，可将 `retrieval` 替换为 FAISS、Milvus 或 Elasticsearch 向量索引，而不改变排序与前端契约。

当前导入任务以磁盘 JSON 持久化，每份结构化结果独立写文件，避免大批量任务竞争修改单一 JSON。多实例生产部署时，可将任务状态与队列替换为 PostgreSQL + Redis/Celery，接口契约保持不变。

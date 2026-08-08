# 切片二：只读 SQL 查询工具（DuckDB）

## 目标

把"整份 CSV 读进内存再用 Python 筛选"升级为"DuckDB 只读 SQL 查询"，作为后续
LangGraph Agent 的标准数据工具。CSV 仍是数据源，DuckDB 直接查询 CSV，不建仓库。

## 范围

- 新增 `tools/sql_tool.py`：
  - `query_quality_data(csv_path, start_date, end_date, production_line, vehicle_model, columns, limit)`
    高层筛选查询，全参数绑定，输出结构化 dict。
  - `run_readonly_query(csv_path, sql, limit)` 底层只读 SQL 入口（供未来 LLM 工具调用）。
- 新增 `tests/test_sql_tool.py`。
- 更新 `README.md` 代码结构一节。

## 安全边界（对应 md 切片二验收）

- 仅允许单条 `SELECT`/`WITH` 语句；拒绝多语句。
- 黑名单关键字：INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH/COPY/PRAGMA/SET 等。
- 禁止任意文件读取函数（read_csv/read_parquet/glob/外部数据库 scan）。
- 表白名单：仅 `production_records`（内部视图，映射到指定 CSV）；FROM/JOIN 引用校验。
- 列白名单：`query_quality_data` 的 columns 参数仅允许 `FIELDNAMES` 中的列。
- 强制 LIMIT，默认 5000，上限 10000。

## 验收标准

1. 可按日期范围、产线、车型查询，结果与现有 `filter_records` 一致。
2. 恶意/写操作 SQL（DROP、DELETE、ATTACH、多语句、任意文件读取）被 ValueError 拒绝。
3. 输出为结构化 dict：status/row_count/records/filters/evidence。
4. `python -m unittest discover -s tests -v` 全绿。

## 不做

- 不接入 PostgreSQL，不改现有 `filter_records` 调用方，不做 LLM 生成 SQL。

---

# 切片三：异常分析工具

## 目标

补齐 md 阶段二要求的两个分析函数，作为 Agent 的"计算内核"：找到不良率
突变发生的日期，以及工艺参数（温度/压力/扭矩）的异常记录。纯确定性逻辑，
先于 LangGraph 完成，保证可独立测试验证。

## 范围

- 新增 `analytics/trend_analysis.py`：
  - `detect_trend_change(records, window=7, min_daily_samples=10)` — 按天聚合不良率，
    比较每个日期前后各 `window` 天窗口的均值差，返回变化最大的跳变点。
- 新增 `analytics/anomaly_detection.py`：
  - `detect_anomalies(records, numeric_fields, contamination=0.05, min_samples=50)` —
    Isolation Forest（`random_state=42` 保证确定性），标记离群记录。
- 新增 `tools/anomaly_tool.py`：Agent 调用层，包装两个函数并附排查建议（中文）。
- 新增 `tests/test_trend_analysis.py`、`tests/test_anomaly_detection.py`。
- 更新 `README.md` 代码结构。

## 输出契约

- `detect_trend_change`：`{status: change_detected|no_change, change_date, before_rate_percent,
  after_rate_percent, change_percent, window, daily_rates, evidence}`。
  样本不足或无跳变时 `status="no_change"`，不报假信号。
- `detect_anomalies`：`{status, sample_count, anomaly_count, anomaly_rate_percent,
  anomalies:[{record_id, timestamp, production_line, workstation, 字段值...}], evidence}`。
  样本 < min_samples 时 `status="insufficient_data"`。

## 验收标准

1. 构造"前低后高"60 天数据，跳变点落在高低分界日，数值可手工验证。
2. 无跳变/数据过少时不报假信号。
3. 注入明显离群点能被检出；同数据重复运行结果一致（确定性）。
4. 全量测试绿。

## 不做

- 不做因果推断、不做预测模型、不改 `app.py` 展示。

---

# 切片四：LangGraph Agent 工作流

## 目标

用 LangGraph 把"问题解析 → 数据查询 → 分析 → 报告"编排成有状态节点图，
工具调用顺序可追踪。保持 `QualityAgent.answer()` 的签名和报告契约不变，
`app.py`/`run_demo.py` 无需改动。

## 范围

- 新增 `agent/state.py`：`QualityState`（TypedDict）与初始状态。
- 新增 `agent/graph.py`：`build_graph()` — 节点 parse → query → analyze → report，
  no_data 条件边直接到 report；每个节点向 `trace` 追加调用记录。
- 重写 `agent/workflow.py`：`QualityAgent` 内部改为调用编译后的图，
  输出契约不变并追加 `trace` 字段；`parse_question`、`render_text_report` 保留。
- 新增 `tests/test_langgraph_workflow.py`。
- 更新 `README.md`。

## 验收标准（md 切片四）

1. 5 个预置问题（不同日期/产线/无数据）都能完成，无数据时走 no_data 分支。
2. `report["trace"]` 显示工具调用顺序：parse_question → filter/query → analyze → report。
3. 现有测试契约（status/question/filters/baseline/top_factors/summary）不变，全量绿。

## 不做

- 不接 LLM（`parse_question` 保持确定性，LLM 结构化输出留到后续）。
- 不改 `app.py` 展示层。

---

# 切片六：固定问题集评测

## 目标

建立固定问题集（≥20 个）和指标统计脚本，形成可复用的验收基线：
每次改动后跑同一套评测，对比指标。这是后续 RAG/LLM 改造的度量前提。

## 范围

- 新增 `evaluation/cases.json`：20 个固定问题，覆盖：
  - 不同时间范围（1-15/1-31/15-31/全线）
  - 产线 A/B、车型、工位提问
  - 无数据（2027 年）、无日期、无有效信息、英文提问
  - 部分 case 带数值断言（`expected_status`/`expected_line`/`expected_dimensions`）
- 新增 `evaluation/evaluate.py`：
  - `load_cases(path)` 读问题集
  - `run_case(agent, case)` 单题执行，返回状态、断言结果、耗时
  - `run_evaluation(agent, cases)` 汇总指标：任务完成率、数值准确率、
    平均响应时间、状态分布
  - `main()` 命令行入口
- 新增 `tests/test_evaluate.py`。
- 更新 `README.md`。

## 指标定义

- **任务完成率**：报告 status 与 `expected_status`（缺省为 success）一致的比例。
- **数值准确率**：有断言 case 中 `expected_line`/`expected_dimensions` 全部通过的比例。
- **平均响应时间**：全部 case 平均耗时（ms）。

## 不做

- 不做人工确认节点、失败重试、日志（md 切片六后半，留后续）。
- 不改 `app.py`。

---

# 切片五：质量知识库与引用

## 目标

给 Agent 建一个本地质量知识库（3 份 markdown 文档），回答时能检索并给出
文档引用；检索不到时明确说明，不编造来源（md 切片五验收）。

## 范围

- 新增 `docs/` 三份文档：`quality_standard.md`（质量标准）、
  `defect_code_manual.md`（缺陷代码手册）、`maintenance_cases.md`（维修案例）。
- 新增 `rag/ingest.py`：读取 docs/*.md，按 `##` 标题切分段落，生成 `rag/index.json`。
- 新增 `rag/retriever.py`：字符 bigram 打分检索（零新依赖、确定性），
  `retrieve(query, documents, top_k, min_score)`。
- 新增 `tools/knowledge_tool.py`：`retrieve_quality_documents(query, top_k)`
  Agent 工具，输出 `{status, query, results, evidence}`，无命中时
  `status="no_results"`。
- `agent/graph.py` 增加 knowledge 节点（analyze → knowledge → report），
  报告新增 `knowledge_refs` 与 `knowledge_summary`。
- `app.py` 在"分析依据"展开区展示知识库引用。
- 新增 `tests/test_rag.py`；更新 trace 顺序断言。

## 验收标准

1. "扭矩偏低"检索命中 `defect_code_manual.md`；"W-07" 命中维修案例。
2. 无关查询返回空并明确 `no_results`，不编造来源。
3. 同查询两次结果一致（确定性）。
4. 报告含 `knowledge_refs`（文档名/章节/摘要）与 `knowledge_summary`；全量测试绿。

## 不做

- 不用 embedding/向量库/LLM；不做文档新增后的增量更新。

---

# 切片七：可插拔 LLM 问题解析

## 目标

把规则版 `parse_question` 升级为"可插拔 LLM 解析后端"，解决 3 个已知失败
案例（车型、中文日期、复合产线），同时保证：无 key、连不上、答得不规范时
自动回退规则解析，评测基线不丢。

## 三种后端（环境变量 `QUALITY_LLM_PROVIDER`，默认 mock）

- `mock`：模拟器——本地规则解析（含中文日期、车型、复合产线），确定性，
  用于开发与测试。
- `ollama`：本地 Ollama（OpenAI 兼容端点 http://localhost:11434/v1，
  模型 `QUALITY_LLM_MODEL` 默认 qwen2.5:7b）。
- `glm`：智谱 GLM（OpenAI 兼容端点，密钥 `GLM_API_KEY`，
  模型默认 glm-4-flash）。

## 设计

- 新增 `agent/llm_parser.py`：
  - `make_parse_fn(provider)` 返回 `(question) -> filters` 的解析函数。
  - `parse_with_llm(question, provider)`：调用后端 → 校验清洗 → 与规则结果
    合并（LLM 漏掉的字段用规则补齐）→ 任何异常回退规则解析。
- `tools/quality_tools.filter_records` 的 `production_line` 支持
  `str | list[str]`，支持复合产线。
- `agent/graph.py` 的 `build_graph(parse_fn=parse_question)` 注入解析函数；
  `QualityAgent(records, llm_provider=None)` 默认 mock。

## 评测扩展

- `cases.json` 20 → 22 题：新增中文日期题、车型题。
- `run_case` 新增 `expected_start_date` / `expected_vehicle_model` 断言。

## 验收标准

1. mock 模式解析：`1月1日到1月15日`、`ID.4 车型`、`A产线和B产线` 全部正确。
2. LLM 输出坏 JSON / 类型错 / 网络失败 → 回退规则解析，结果可用。
3. LLM 漏字段 → 规则字段补齐（合并）。
4. 评测 22 题全绿；全量测试绿。

## 不做

- 不做对话记忆、不做 Function Calling 多轮，不接向量库。






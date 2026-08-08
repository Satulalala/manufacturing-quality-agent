# Agent 开发学习路线与制造质量根因分析项目

## 1. 项目定位

本项目面向新能源汽车制造场景，目标是实现一个“制造质量根因分析 Agent”。

用户可以用自然语言提问：

> 请分析 2026 年 1 月 1 日至 1 月 15 日 A 产线的不良率异常，找出最值得优先排查的三个因素，并给出数据依据和相关质量案例。

Agent 需要完成：

1. 解析问题中的时间、车型和产线。
2. 查询生产和质量数据。
3. 计算不良率、趋势和分组差异。
4. 调用异常检测工具。
5. 排序候选影响因素。
6. 检索质量标准、维修手册和历史案例。
7. 输出带数据证据、文档引用和不确定性说明的报告。

注意：第一版输出应称为“候选原因”或“优先排查因素”，不能把统计相关性直接描述为已经证明的因果关系。

## 2. 推荐技术栈

### 第一版

- Python 3.11+
- Pandas、NumPy、SciPy、scikit-learn
- SQL：DuckDB（本地开发简单，支持直接查询 CSV）
- Agent：LangGraph
- LLM：可配置的云端模型 API
- RAG：LlamaIndex 或 LangChain + FAISS/Chroma
- 后端：FastAPI
- 演示界面：Streamlit
- 测试：pytest
- 部署：Docker
- 版本管理：Git + GitHub

### 第二版

- DuckDB 替换或并行支持 PostgreSQL
- FAISS/Chroma 替换为 pgvector 或 Qdrant
- 增加 Evidently 做数据和模型监控
- 增加结构化日志、调用链和成本统计

不要一开始同时引入 LangChain、LangGraph、LlamaIndex、AutoGen 等多个框架。第一版选择 LangGraph 作为工作流框架即可。

## 3. 学习路线

## 阶段一：Python、SQL 和工程基础（第 1-2 周）

### 学习目标

- 能独立读取、清洗和分析 CSV 数据。
- 能用 SQL 完成多表关联、聚合和窗口统计。
- 能把 Python 函数封装为 API。
- 能用 Git 管理项目，用 Docker 运行服务。

### 必学内容

- Python：函数、类、异常处理、类型注解、虚拟环境
- SQL：JOIN、GROUP BY、窗口函数、CTE、子查询
- 数据处理：Pandas、NumPy、缺失值和异常值处理
- Web：HTTP、JSON、REST API、FastAPI
- 工程：Git、日志、配置文件、环境变量

### 阶段验收

给定生产数据后，能够输出：

- 指定时间段的不良率
- 不同产线、工位、班次和供应商的不良率对比
- 不良率趋势图
- 缺陷类型 Pareto 图

## 阶段二：制造质量和异常分析（第 3-4 周）

### 需要理解的业务概念

- 不良率、一次通过率、返修率
- OEE、节拍、停机时间
- SPC 和控制图
- Pareto 分析
- 5 Why 根因分析
- FMEA
- Cp、Cpk
- 批次、工位、班次、供应商和车型

### 建议实现的传统分析函数

```python
calculate_defect_rate()
compare_groups()
detect_trend_change()
detect_anomalies()
rank_candidate_causes()
```

候选因素可以先用以下方法排序：

- 分组不良率与总体不良率的差异
- 风险比或提升倍数
- 相关系数和互信息
- Isolation Forest 等异常检测
- 分类模型的特征重要性

统计结果需要同时展示样本量，避免小样本造成误判。

### 推荐数据集

- [AI4I 2020 Predictive Maintenance Dataset](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset)：入门和设备异常分析。
- [SECOM](https://archive.ics.uci.edu/dataset/179/secom)：半导体生产质量和高维缺陷分析。
- [Bosch Production Line Performance](https://www.kaggle.com/c/bosch-production-line-performance)：生产线质量预测和高维特征工程。

建议先使用 AI4I 跑通流程，再使用 SECOM 或 Bosch 做进阶版本。

## 阶段三：LLM 应用开发（第 5-6 周）

### 学习顺序

1. 模型 API 调用
2. Prompt 和结构化 JSON 输出
3. Function Calling/Tool Calling
4. Embedding 和向量检索
5. RAG
6. 对话状态和错误处理

### 推荐学习仓库

- [LangGraph](https://github.com/langchain-ai/langgraph)：工作流、状态、工具调用和人工介入。
- [LlamaIndex](https://github.com/run-llama/llama_index)：文档检索、SQL 查询引擎和 RAG。
- [PyOD](https://github.com/yzhao062/pyod)：异常检测算法。
- [Evidently](https://github.com/evidentlyai/evidently)：数据和模型监控。

## 阶段四：Agent 工程化（第 7-8 周）

重点学习：

- 有状态工作流
- 工具权限控制
- SQL 只读和查询白名单
- 工具调用失败重试
- 超时和降级处理
- 人工审核节点
- 日志和调用链
- 固定问题集评测
- 结果引用和可追溯性

企业 Agent 的核心不是“能聊天”，而是“可控、可评估、可追溯”。

## 阶段五：项目整理和面试准备（第 9-10 周）

需要准备：

- GitHub README
- 系统架构图
- 数据库表结构图
- Agent 执行流程图
- 3 个成功案例
- 3 个失败案例
- 评测结果
- 3 分钟项目演示视频或录屏
- 一页简历项目描述

## 4. 项目目录

```text
manufacturing-quality-agent/
├── data/
│   ├── raw/
│   └── processed/
├── docs/
│   ├── quality_standard.md
│   ├── defect_code_manual.md
│   ├── production_process.md
│   └── maintenance_cases.md
├── analytics/
│   ├── defect_rate.py
│   ├── trend_analysis.py
│   ├── anomaly_detection.py
│   └── root_cause.py
├── tools/
│   ├── sql_tool.py
│   ├── quality_tool.py
│   ├── anomaly_tool.py
│   ├── knowledge_tool.py
│   └── report_tool.py
├── agent/
│   ├── state.py
│   ├── graph.py
│   └── prompts.py
├── rag/
│   ├── ingest.py
│   └── retriever.py
├── api/
│   └── main.py
├── evaluation/
│   ├── cases.json
│   └── evaluate.py
├── tests/
│   ├── test_analytics.py
│   └── test_tools.py
├── app.py
├── requirements.txt
├── Dockerfile
└── README.md
```

## 5. 数据表设计

### production_records

```text
record_id          生产记录 ID
timestamp          生产时间
vehicle_model      车型
production_line    产线
workstation        工位
shift              班次
supplier_id        供应商
batch_id           批次
temperature        温度
pressure           压力
torque             扭矩
result             OK 或 NG
```

### defects

```text
defect_id          缺陷 ID
record_id          对应生产记录
defect_type        缺陷类型
severity           严重程度
repair_result      维修结果
```

### maintenance_cases

```text
case_id            案例 ID
vehicle_model      车型
symptom            故障现象
root_cause         历史根因
solution           处理方案
created_at         创建时间
```

## 6. 按垂直切片开发

### 切片一：普通质量分析

实现读取数据、计算不良率、分组对比和趋势图。

验收标准：同一份数据重复运行，结果稳定，关键数字可以手工验证。

### 切片二：查询工具

实现安全的只读 SQL 查询工具，限制可访问的表和字段。

验收标准：可以查询指定日期、产线和车型；恶意或修改数据的 SQL 会被拒绝。

### 切片三：分析工具

实现异常检测和候选因素排序。

验收标准：输出因素、指标、样本量和计算依据，而不是只输出一句自然语言结论。

### 切片四：Agent 工作流

使用 LangGraph 串联问题解析、数据查询、分析和报告生成。

验收标准：Agent 能完成 5 个预先准备的问题，并且工具调用顺序可追踪。

### 切片五：质量知识库

导入质量标准、缺陷代码和历史维修案例，支持检索和引用。

验收标准：回答中给出文档名称和相关段落；检索不到时明确说明，不编造来源。

### 切片六：评测和人工审核

增加固定问题集、日志、失败重试和人工确认节点。

验收标准：能统计任务完成率、SQL 成功率、数值准确率、引用准确率和平均响应时间。

## 7. Agent 工具设计

建议先实现以下工具：

```text
query_quality_data()
calculate_defect_rate()
compare_production_groups()
detect_quality_anomalies()
rank_candidate_causes()
retrieve_quality_documents()
generate_quality_report()
```

工具输出使用结构化数据，例如：

```json
{
  "status": "success",
  "factor": "workstation",
  "value": "W-07",
  "defect_rate": 0.087,
  "baseline_rate": 0.021,
  "sample_count": 126,
  "evidence": ["production_records:2026-01-01~2026-01-15"]
}
```

## 8. 最终展示流程

```text
用户输入问题
    ↓
Agent 解析时间、车型和产线
    ↓
调用 SQL 查询工具
    ↓
计算不良率和分组差异
    ↓
调用异常检测工具
    ↓
检索质量标准和历史案例
    ↓
输出候选原因、证据、建议和不确定性
    ↓
人工确认或继续追问
```

最终页面至少包含：

- 问题输入框
- 执行过程或工具调用记录
- 不良率趋势图
- 候选因素排名
- 数据证据
- 知识库引用
- 风险提示
- 人工确认按钮

## 9. 评测指标

准备 20-50 个固定问题，至少覆盖：

- 时间范围不同
- 产线和车型不同
- 问题类型不同
- 数据不足
- 没有相关知识文档
- 工具执行失败

记录以下指标：

- 任务完成率
- SQL 执行成功率
- 数值准确率
- 候选因素命中率
- 引用准确率
- 平均响应时间
- 平均 Token 或调用成本
- 人工审核通过率

## 10. 简历项目描述

可以写成：

> 面向新能源汽车制造质量场景，基于 LangGraph 设计制造质量根因分析 Agent，集成 DuckDB SQL 查询、异常检测、质量知识库 RAG 和结构化报告生成工具；支持按产线、工位、班次和供应商分析不良率异常，输出候选影响因素、数据证据及相关质量案例，并通过固定问题集评估任务完成率和引用准确率。

## 11. 面试重点

需要能够解释：

- Agent 和普通聊天机器人的区别。
- 为什么要把统计分析封装成工具，而不是让模型直接计算。
- 如何防止模型生成错误 SQL。
- 如何防止 RAG 答案没有依据。
- 相关性为什么不等于因果性。
- 多 Agent 是否真的有必要。
- 工具调用失败时如何重试和降级。
- 如何评估 Agent 的效果。
- 如何处理高压电池、制动等高风险场景。

## 12. Definition of Done

项目完成的最低标准：

- [ ] 能本地启动并完成一次完整分析。
- [ ] 至少有 3 个可复现的演示问题。
- [ ] 分析结果包含数字、样本量和证据。
- [ ] 知识库回答包含来源引用。
- [ ] SQL 工具是只读且有限制的。
- [ ] 至少有 20 个评测问题。
- [ ] 有成功和失败案例说明。
- [ ] README 包含架构图、启动方式和 Demo 截图。
- [ ] 代码可以通过基础测试和语法检查。

## 13. 最小可行版本

如果时间有限，只完成以下内容：

1. AI4I 或自制模拟数据。
2. DuckDB 查询。
3. 不良率和分组异常分析。
4. LangGraph 单 Agent 工作流。
5. 3 个质量文档的 RAG 检索。
6. Streamlit 演示页面。
7. 20 个问题的评测集。

完成这个版本后，再考虑 PostgreSQL、Qdrant、Docker、监控和多 Agent。核心目标是先做出一个“可运行、可解释、可评测”的业务闭环。

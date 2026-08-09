# Manufacturing Quality Root Cause Agent

面向新能源汽车制造场景的制造质量根因分析 Agent MVP。

GitHub 仓库：https://github.com/Satulalala/manufacturing-quality-agent

当前版本采用"确定性分析内核 + 可选本地 LLM"架构：质量分析全部由确定性
Python 函数完成（数字可复现、可测试、可追溯），问题解析和知识检索可选用
本地 Ollama 模型（工业数据不出厂），无模型时自动回退规则解析。

## 功能一览

- **自然语言提问**：可插拔 LLM 解析后端，支持标准日期、中文日期（1月1日）、
  车型（ID.4）和复合产线（A产线和B产线）；无 key 或连不上时自动回退规则解析。
  三种后端：`mock`（模拟器，默认）/ `ollama`（本地模型）/ `glm`（智谱云端）。
- **不良率分析**：计算指定范围的总不良率、缺陷数量、样本量。
- **候选因素排名**：按工位、班次、供应商、批次分组对比，排出最值得优先排查的
  前 3 个因素（带不良率、样本量、数据证据和人工确认建议）。
- **质量分析工具箱**：Pareto 缺陷类型分析（占比/累计占比）、Cpk 工艺能力
  指数（capable/marginal/not_capable 分级）、SPC 控制线检测（超限点定位）。
- **趋势跳变检测**：前后窗口对比，定位不良率突变发生的日期。
- **参数异常检测**：Isolation Forest 检出温度/压力/扭矩的离群记录（结果确定）。
- **知识库引用**：语义向量检索（本地 bge-m3 embedding），问"螺丝拧不紧"也能
  命中"扭矩偏低"案例；Ollama 不可用时自动回退关键词检索；无命中明确说明。
- **调用链追踪**：页面展示完整执行过程（解析 → 筛选 → 分析 → 知识库 → 报告），
  每次工具调用附记录，全流程可审计。
- **结构化运行日志**：每次分析写入 `logs/run_*.json`（问题、筛选条件、每步
  耗时、状态、不良率、候选因素、人工确认标记），可追溯可统计。
- **工具失败重试**：LLM 调用、SQL 执行自动重试（指数退避），网络抖动不降级。
- **人工确认标记**：统计候选结论带 `requires_human_review` 标记，页面提供
  "标记为已确认"按钮，符合"相关性不等于因果性"的工业约束。
- **解析条件回显**：页面显示本次问题解析出的查询条件（日期范围/产线/车型），
  发现解析不对可以立即看到。
- **知识库引用卡片**：命中时以卡片展示文档名、章节和原文摘要；未命中明确说明。
- **只读 SQL 工具**：DuckDB 查询，表/列白名单，恶意 SQL 被拒绝。
- **固定问题集评测**：22 道题自动评测，统计完成率、准确率和响应时间。

## 快速运行

要求：Python 3.10 或更高版本。

### 可视化页面

最简单的方式是直接双击项目目录中的：

```text
start_dashboard.bat
```

也可以使用 PowerShell 手动启动。

安装页面依赖：

```powershell
python -m pip install streamlit pandas matplotlib duckdb scikit-learn langgraph
```

启动页面：

```powershell
python -m streamlit run app.py
```

浏览器打开 `http://localhost:8501`。

### 命令行版本

```powershell
python run_demo.py
```

也可以输入自己的问题：

```powershell
python run_demo.py "请分析 2026-01-01 到 2026-01-15 B产线的不良率异常"
```

第一次运行会生成 `data/demo_records.csv`。数据是可复现的模拟数据，不代表任何
真实企业生产数据。

### 评测

```powershell
# mock（规则模拟器，默认，毫秒级）
python evaluation/evaluate.py

# 真实 LLM（Ollama 本地模型，约 7 秒/题）
python evaluation/evaluate.py --provider ollama
```

### 切换 LLM 解析后端

```powershell
# 模拟器（默认，规则解析，无需任何配置）
set QUALITY_LLM_PROVIDER=mock

# 本地 Ollama（需先安装 https://ollama.com 并拉取模型）
ollama pull qwen2.5:7b
set QUALITY_LLM_PROVIDER=ollama

# 智谱 GLM（免费模型，需注册 https://bigmodel.cn 获取 API key）
set QUALITY_LLM_PROVIDER=glm
set GLM_API_KEY=你的key
```

任何后端失败（网络、格式错、无 key）都会自动回退到规则解析，不影响使用。

## 运行测试

项目使用 Python 标准库 `unittest`：

```powershell
python -m unittest discover -s tests -v
```

> 部分用例（向量检索）调用本地 Ollama，全量约 6 分钟；不启动 Ollama 时
> 这些用例自动回退到关键词检索路径，测试仍可通过。

## 系统架构

```mermaid
flowchart LR
    subgraph UI[展示层]
        App[Streamlit 分析台 app.py<br/>根因分析 + 质量工具箱]
        CLI[命令行 run_demo.py]
        Eval[评测 evaluation/evaluate.py]
    end
    subgraph Agent[Agent 编排层]
        Graph[LangGraph 状态图<br/>agent/graph.py]
    end
    subgraph Tools[工具层]
        P[parse 问题解析<br/>mock/ollama/glm 可插拔]
        Q[filter_records 数据筛选]
        A[质量分析<br/>不良率/趋势/异常/Pareto/Cpk/SPC]
        K[知识库检索<br/>向量 bge-m3 + bigram 回退]
        S[run_readonly_query<br/>DuckDB 只读 SQL]
        R[retry 重试 / run_logger 日志]
    end
    subgraph Data[数据与知识层]
        CSV[(data/demo_records.csv<br/>2400 条模拟记录)]
        Docs[(docs/ 质量文档<br/>标准/缺陷手册/案例)]
    end
    subgraph Local[本地模型层]
        Ollama[(Ollama<br/>qwen2.5:7b + bge-m3)]
    end
    UI --> Graph
    Graph --> P & Q & A & K
    P --> Ollama
    K --> Ollama
    Q --> CSV
    S --> CSV
    K --> Docs
```

## Agent 执行流程

```mermaid
flowchart TD
    Q[自然语言问题] --> P[parse_question 提取日期/产线]
    P --> F[filter_records 安全筛选记录]
    F --> D{有匹配数据?}
    D -- 否 --> ND[no_data<br/>诚实报告，不编造结论]
    D -- 是 --> B[calculate_defect_rate 基线不良率]
    B --> R[rank_candidate_causes 候选因素排序]
    R --> TR[detect_trend_change 趋势跳变]
    R --> AN[detect_anomalies 参数异常]
    R --> K[retrieve_quality_documents 知识库检索]
    TR & AN & K --> G[generate_report 结构化报告]
    G --> OUT[结论 + 数据证据 + 样本量<br/>知识库引用 + 调用链 + 风险提示]
```

## 评测结果（2026-08-09，demo_records.csv，2400 条，mock 解析后端）

| 指标 | 结果 |
|---|---|
| 任务完成率 | 22/22 = 100% |
| 数值准确率 | 14/14 = 100% |
| 候选因素命中率 | 100% |
| 引用准确率 | 100% |
| SQL 成功率 | 6 条检查（3 合法 + 3 恶意）= 100% |
| 人工审核通过率 | 20/20 = 100% |
| 平均响应时间 | 约 3.2 s（含向量检索） |
| 状态分布 | success 20，no_data 2 |

qwen2.5:7b（Ollama 本地）解析后端下，完成率与数值准确率同样为 100%，
平均响应时间约 7 s。

## 成功与失败案例

详见 [docs/cases.md](docs/cases.md)。摘要：

**成功案例**
1. A 产线 1 月上半月分析：命中 W-07（19.72%）、Night（10.44%）、S-03（10.14%），
   与数据中注入的缺陷模式一致，知识库自动引用对应维修案例。
2. 趋势跳变检测：自动定位到 2026-01-16 前后不良率跳变 +3.76 个百分点。
3. 无数据场景：2027 年查询返回 `no_data` 并明确说明，不编造结论。

**已修复的失败案例（LLM 解析后端）**
1. 车型问题：`ID.4 车型` 现在能正确解析为 `vehicle_model=ID.4`。
2. 中文日期：`1月1日到1月15日` 现在能正确转换为 `2026-01-01 ~ 2026-01-15`。
3. 复合产线：`A产线和B产线` 现在解析为 `["A", "B"]`，两条产线都参与统计。

## 代码结构

```text
analytics/quality_analysis.py  纯 Python 质量分析函数
analytics/trend_analysis.py    不良率趋势跳变检测（前后窗口对比）
analytics/anomaly_detection.py Isolation Forest 工艺参数异常检测
analytics/pareto.py            缺陷类型 Pareto 分析（占比/累计占比）
analytics/process_capability.py Cp/Cpk 工艺能力指数
analytics/spc_analysis.py      SPC 控制线与超限点检测
data/demo_data.py              可复现模拟数据和 CSV 读写
docs/                          质量知识库（标准/缺陷手册/维修案例）与项目文档
rag/ingest.py                  知识文档切分与索引（显式文件名白名单）
rag/retriever.py               字符 bigram 确定性检索（回退用）
rag/embedding.py               本地 Ollama embedding 客户端（bge-m3）
rag/vector_retriever.py        语义向量检索（余弦相似度）+ 向量索引
tools/quality_tools.py         Agent 可调用的数据筛选工具
tools/sql_tool.py              DuckDB 只读 SQL 查询工具（表/列白名单）
tools/anomaly_tool.py          趋势/异常检测的 Agent 调用包装层
tools/capability_tool.py       Pareto/Cpk/SPC 的 Agent 调用包装层
tools/knowledge_tool.py        知识库检索工具（无命中时明确说明）
agent/workflow.py              Agent 公共入口和报告渲染（兼容层）
agent/graph.py                 LangGraph 节点图（parse→query→analyze→knowledge→report）
agent/state.py                 LangGraph 状态定义
agent/llm_parser.py            可插拔 LLM 解析（mock/ollama/glm，自动回退规则）
agent/run_logger.py            结构化运行日志（logs/run_*.json）
tools/retry.py                 工具调用重试（指数退避）
app.py                         Streamlit 可视化分析台
run_demo.py                    命令行入口
evaluation/cases.json          固定问题集（22 题）
evaluation/evaluate.py         评测：任务完成率/数值准确率/响应时间
tests/                         单元测试（91 个）
tasks/plan.md                  切片二至十的开发规格与验收记录
```

## 简历项目描述

> 面向新能源汽车制造质量场景，基于 LangGraph 设计制造质量根因分析 Agent，
> 集成 DuckDB 只读 SQL 查询、异常检测、Pareto/Cpk/SPC 质量分析工具、语义
> 向量检索知识库（本地 bge-m3，支持同义表达召回）和结构化报告生成；问题
> 解析采用可插拔 LLM 后端（本地 Ollama qwen2.5:7b，工业数据不出厂，失败
> 自动回退规则），含工具失败重试、人工审核标记与结构化调用日志；通过 22
> 题固定问题集八项指标评估（任务完成率/数值准确率/因素命中率/引用准确率/
> SQL 成功率/审核通过率/响应时间）全部 100%。

## 下一步扩展

1. 支持 Function Calling 与对话记忆，让 LLM 直接驱动工具调用。
2. 使用 DuckDB/PostgreSQL 替代直接加载 CSV 到内存。
3. 用 AI4I 等真实数据集替换模拟数据，做进阶演示。
4. 增加 Docker 部署和可观测性（调用链、耗时、成本统计）。
5. 评测补全引用准确率、SQL 成功率、人工审核通过率指标。

## 重要限制

候选因素是基于分组统计差异的优先级排序，不等于已证明的因果关系。进入真实
生产环境前，需要接入经过授权的数据、权限控制、人工审核和更严格的工业安全
流程。当前问题解析仅支持有限的日期格式和产线词汇，详见 docs/cases.md。

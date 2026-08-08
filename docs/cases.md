# 成功与失败案例

所有案例基于 `data/demo_records.csv`（2400 条可复现模拟数据，seed=42），
通过 `python run_demo.py` / `python -X utf8 -c "..."` 实测记录。

## 成功案例

### 案例一：A 产线 1 月上半月不良率异常（完整链路）

问题：`请分析 2026-01-01 到 2026-01-15 A产线的不良率异常`

实际输出：

```text
状态：success
结论：共分析 611 条记录，不良率为 7.20%。 候选因素：workstation=W-07；shift=Night；supplier_id=S-03。
数据：611 条，缺陷 44 条，不良率 7.20%
候选因素：
1. workstation=W-07，不良率 19.72%，样本 71；优先检查该工位的设备参数、工装状态和最近换型记录。
2. shift=Night，不良率 10.44%，样本 297；对比该班次的交接班记录、人员配置和作业参数。
3. supplier_id=S-03，不良率 10.14%，样本 148；核查该供应商批次、来料检验记录和近期变更。
知识库引用：
- maintenance_cases.md（案例一：W-07 扭矩偏低批量不良）
- maintenance_cases.md（案例二：夜班压力偏高）
- maintenance_cases.md（案例三：S-03 供应商批次温度漂移）
调用链：parse_question → filter_records → rank_candidate_causes → retrieve_quality_documents → generate_report
```

要点：排名前三的因素与模拟数据注入的缺陷模式（W-07 +13%、Night +4.5%、S-03
+3.5%）完全吻合；知识库检索自动命中对应维修案例；每个因素带样本量和证据。

### 案例二：B 产线全月分析

问题：`请分析 2026-01-01 到 2026-01-31 B产线的不良率`

实际输出摘要：

```text
状态：success
结论：共分析 1167 条记录，不良率为 6.86%。 候选因素：workstation=W-07；batch_id=B-054；shift=Night。
```

要点：不同产线、不同时间范围均能正确完成；候选因素随筛选范围动态变化。

### 案例三：无数据场景（诚实报告）

问题：`请分析 2027-01-01 到 2027-01-02 A产线的不良率`

实际输出：

```text
状态：no_data
结论：没有符合条件的生产记录，无法生成质量结论。
数据：0 条，缺陷 0 条，不良率 0.00%
知识库：未检索到与问题相关的知识库文档，不编造来源。
调用链：parse_question → filter_records → generate_report
```

要点：数据范围外的问题不编造结论，明确报告 no_data；知识库无命中时也如实
说明。这是评测集中 2 道 no_data 题的预期行为。

## 失败案例（已修复，切片七）

以下三个案例在早期规则解析版本（`parse_question`）中存在，切片七接入可插拔
LLM 解析后端（默认 `mock`）后已全部解决，保留记录作为项目演进过程的说明。

### 案例四：车型参数未解析（已修复）

早期行为：`filters` 中无 `vehicle_model`，ID.4 被静默忽略。

当前行为（mock 后端）：

```text
> 请分析 2026-01-01 到 2026-01-31 ID.4 车型的不良率异常
filters = {'start_date': '2026-01-01', 'end_date': '2026-01-31',
           'production_line': None, 'vehicle_model': 'ID.4'}
```

### 案例五：中文日期格式未解析（已修复）

早期行为：`1月1日` 无法匹配 `20xx-xx-xx` 正则，日期过滤失效且无提示。

当前行为（mock 后端）：

```text
> 请分析 1月1日到1月15日 A产线
filters = {'start_date': '2026-01-01', 'end_date': '2026-01-15',
           'production_line': ['A'], 'vehicle_model': None}
```

### 案例六：复合产线只取第一个（已修复）

早期行为：`A产线和B产线` 只解析出 A，B 被忽略。

当前行为（mock 后端）：

```text
> 请分析 2026-01-01 到 2026-01-31 A产线和B产线的不良率
filters = {'start_date': '2026-01-01', 'end_date': '2026-01-31',
           'production_line': ['A', 'B'], 'vehicle_model': None}
```

### 仍然存在的限制

- 规则解析只认 `20xx-xx-xx` 日期格式（mock 后端额外支持中文日期）。
- 复合产线的排序按字母序；"产线和产线"等混合表达依赖正则组合，极端写法
  可能漏识别——这正是接入真实 LLM 后要覆盖的场景。

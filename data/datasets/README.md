# 多年度汽车装配质量数据集（合成）

此目录包含 2022–2026 年的五份可复现 CSV。所有记录和标识符均由本项目程序生成，工厂、车型、供应商、人员、设备和批次均为虚构，不代表任何真实车企或供应链。

## 数据范围

| 文件 | 时间范围 | 记录数 | 用途 |
|---|---|---:|---|
| `quality_records_2022.csv` | 2022-01-01 至 2022-12-31 | 6,000 | 基线与早期过程波动 |
| `quality_records_2023.csv` | 2023-01-01 至 2023-12-31 | 6,000 | 年度改善对比 |
| `quality_records_2024.csv` | 2024-01-01 至 2024-12-31 | 6,000 | 供应商、班次和设备因素分析 |
| `quality_records_2025.csv` | 2025-01-01 至 2025-12-31 | 6,000 | 控制措施变化对比 |
| `quality_records_2026.csv` | 2026-01-01 至 2026-10-18 | 4,500 | 本年度演示与筛选 |

每行代表一条带可追溯标识的整车装配质量检查快照；关键工艺测量值按序列号关联到同一条记录。数据按年份分别提供，便于独立分析及多文件对比。

## 字段口径

- **追溯信息**：`plant_code`、`production_line`、`workstation`、`operation_code`、`vehicle_model`、`part_number`、`serial_number`、`batch_id`、`supplier_id`、`supplier_lot`。
- **生产上下文**：`timestamp` 为 ISO 8601 本地时间（`+08:00`）；`shift` 使用 `Day` / `Night`；`inspection_stage` 使用 `IPQC` / `EOL`。
- **质量控制**：`control_plan_id`、`control_plan_revision`、`characteristic_id`、`characteristic_class`、`sampling_plan`、`reaction_plan_code`。
- **测量及单位**：`torque` 为 N·m、`pressure` 为 kPa、`temperature` 为 °C；每项均包含对应的 `*_lsl` / `*_usl` 规格限字段。数值为模拟过程读数，不应作为现场工艺规格。
- **判定及处置**：`result` 使用 `OK` / `NG`；`defect_type`、`defect_code`、`severity`、`disposition` 和 `rework_flag` 为本项目定义的演示编码，不是 OEM 缺陷码或客户特殊要求。
- **测量系统追溯**：`equipment_id`、`measurement_tool_id`、`operator_id` 和 `traceability_status` 用于练习关联分析；演示数据不包含真实校准证书、人员身份或设备档案。

表头统一使用英文 `snake_case`，类别采用受控编码，测量字段附单位、规格限及记录级追溯信息。异常模式用于练习趋势、分层、Pareto、SPC、Cpk 和根因候选分析；候选相关性不代表因果结论。

## 生成与标准参考

运行 `python -m data.generate_quality_datasets` 可按固定随机种子重建五份数据。数据字段围绕汽车质量管理常见的过程追溯、控制计划、特殊特性、测量系统及统计过程控制概念设计；这只是学习用数据结构，不等同于 IATF 16949、客户特殊要求或 AIAG Core Tools 的符合性证明。

- [AIAG Quality Core Tools](https://www.aiag.org/expertise-areas/quality/quality-core-tools)
- [IATF OEM Customer Specific Requirements](https://www.iatfglobaloversight.org/oem-requirements/customer-specific-requirements/)

正式生产使用时，应以企业受控文件、适用版本的标准、主机厂客户特殊要求和现场批准的控制计划为准。

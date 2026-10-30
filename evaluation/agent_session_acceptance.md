# Agent 会话改造验收矩阵

此矩阵把方案中的 T01–T12 映射到固定数据、脚本化决策器或本地状态测试。脚本化测试只验证流程与程序边界，不代表真实 Ollama 的工具选择成功率。

| 场景 | 自动化覆盖 | 核对结果 |
|---|---|---|
| T01 A 产线切换到 B | `tests.test_conversation_state.test_quality_agent_restores_a_to_b_session_without_changing_month` | 产线变为 B，月份和数据版本保持；两轮报告分别保存。 |
| T02 班次/工位/风险线索 | `tests.test_quality_tool_filters`、`tests.test_conversation_state.test_explicit_workstation_replaces_value_and_inherits_other_dimensions`、`tests.test_agent_loop.test_inspect_group_requires_prior_evidence` | 仅使用白名单筛选维度；细分工位检查需有工具观察支持。 |
| T03 Cpk 缺参后续接 | `tests.test_conversation_state.test_cpk_pending_task_resumes_after_bounds_and_unit_confirmation`、`tests.test_agent_loop.test_controlled_loop_does_not_call_cpk_without_explicit_specs` | 缺规格时不执行；下限、上限、单位确认后沿用同一 task ID 继续。 |
| T04 重启恢复/状态迁移 | `tests.test_conversation_state.test_quality_agent_restores_a_to_b_session_without_changing_month`、`test_new_session_json_state_does_not_import_langgraph`、`test_current_json_state_can_be_exported_for_legacy_rollback` | 会话在应用 SQLite JSON 表恢复；旧 checkpoint 可迁移，新状态可导出回旧格式。 |
| T05 会话隔离 | `tests.test_conversation_state.test_sessions_persist_small_state_and_remain_isolated` | 消息、筛选与报告互不串用。 |
| T06 数据源版本变化 | `tests.test_conversation_state.test_session_rejects_a_changed_dataset_version`、`tests.test_context_manager.test_result_store_persists_tool_output_and_scopes_access_to_session` | 版本不符的会话停止；证据只允许原会话读取。 |
| T07 调用预算耗尽 | `tests.test_agent_loop.test_tool_call_budget_stops_before_excess_execution`、`tests.test_agent_loop.test_repeated_success_uses_cache_and_decision_budget_stops_loop` | 达到工具/决策预算后停止，调用数受上限约束。 |
| T08 越权工具与恶意文档 | `tests.test_agent_loop.test_invalid_tool_is_rejected_before_execution`、`tests.test_agent_loop.test_wrong_filter_echo_is_rejected_before_tool_execution`、`tests.test_agent_loop.test_malicious_document_text_cannot_add_an_unregistered_tool` | 未注册工具和篡改筛选在执行前拒绝；只保留已执行的白名单查询。 |
| T09 超时/工具错误 | `tests.test_ollama_timeout.test_timeout_explains_local_model_delay_and_fails_closed`、`tests.test_agent_loop.test_tool_error_keeps_earlier_evidence_and_cannot_finish_as_success` | 失败不伪装成功；早先有效证据保留，事件写入状态和停止原因。 |
| T10 长对话与预算 | `tests.test_context_manager` | 精确筛选、待办与数据版本优先保留；大记录不进入提示词；必需上下文超预算时拒绝调用。 |
| T11 记忆确认/修改/删除 | `tests.test_memory_store.test_preferences_are_confirmed_versioned_and_owner_scoped`、`tests.test_conversation_state.test_confirmed_response_preference_applies_across_sessions_and_delete_takes_effect` | 用户确认后跨会话生效；修改留版本；删除后不再注入；规格只对精确车型、工位、参数、数据版本和单位生效。 |
| T12 连点与重放 | `tests.test_conversation_state.test_sessions_persist_small_state_and_remain_isolated`、`tests.test_conversation_state.test_unexpected_session_error_is_saved_and_submission_replay_is_finite` | 同一提交回放缓存报告；超过 5 分钟的遗留 running 提交可重新认领；运行事件保留各类 ID。 |

针对性验证命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_loop tests.test_context_manager tests.test_memory_store tests.test_run_logger tests.test_conversation_state tests.test_ollama_timeout tests.test_quality_tool_filters -v
```

运行事件位于 `.cache/quality_agent_events.jsonl`。记录字段包括 session/run/task/tool-call ID、数据版本、状态、耗时、重试数和恢复事件；事件不包含问题正文或工具结果正文。真实 Ollama 的选择质量与延迟需单独记录模型名、版本、样本和时间，不与脚本化测试合并统计。

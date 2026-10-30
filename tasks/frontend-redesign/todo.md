# 独立前端重构任务清单

日期：2026-10-19

状态：主体已实施，验收与剩余交互继续推进。关联方案：[plan.md](./plan.md)。

默认单 Agent 顺序推进；每个任务完成后记录变更与验证结果。文件列表为预估，新任务超过约五个主要文件时继续拆分。

## T01：建立新工作台布局与交互预览

- [x] 建立 React + TypeScript + Vite 工程，固定字体、色彩、间距与焦点规范。
- [x] 实现左侧会话／问题目录、中间聊天、右侧按需结果面板。
- [x] 实现用户右侧消息、Agent 左侧正文、底部输入框和面板切换。
- [x] 预览数据统一标为演示，所有可见操作有实现或明确禁用说明。

验收：1440 与 1280 px 可用；390 px 使用抽屉布局；页面采用独立聊天工作台布局。

验证：前端类型检查、生产构建和浏览器视觉检查；检查长问题、长回复、空会话。

依赖：无。主要文件：frontend/package.json、frontend/index.html、frontend/src/main.tsx、frontend/src/app/Workspace.tsx、frontend/src/app/styles.css。规模：中。

## T02：建立 API 基础与接口契约

- [x] 建立 FastAPI 入口及 /api/v1/health，配置本机监听与开发代理。
- [x] 固定 Source、Session、Message、Run、Artifact、Event DTO 与错误码。
- [x] 规定独立 message_id、submission_id、run_id 的用途与映射。
- [x] 固定数据来源／运行／事件的存储方案和增量迁移策略。

验收：前端通过 API 读取服务状态；模型探测失败时页面仍能打开；前端只依赖公开接口契约。

验证：接口契约测试、Python 导入检查；检查响应不包含数据库路径或完整检查点。

依赖：T01。主要文件：server/main.py、server/schemas.py、server/services/store.py、frontend/src/lib/api.ts、frontend/vite.config.ts。规模：中。

## T03：打通数据源上传与恢复

- [x] 接入演示数据与 CSV 上传，并复用现有 CSV 解析校验。
- [x] 持久化数据源元信息、内容版本和文件。
- [x] 数据管理面板支持列表、分页预览和明确错误提示。
- [x] 输入框选择数据后显示上下文标签。

验收：服务重启后可重新选择已上传数据；无效 CSV 和超限文件被拒绝；前端不能指定服务器读取路径。

验证：上传校验、大小边界、同内容去重与重启恢复测试；浏览器上传一次真实 CSV。

依赖：T02。主要文件：server/routes/sources.py、server/services/sources.py、frontend/src/features/data/DataManager.tsx、frontend/src/lib/api.ts、tests/test_web_sources.py。规模：中。

## T04：打通会话与消息历史

- [x] 接入现有 SessionStore，新建、切换、重命名和分页读取历史。
- [x] 把用户消息、Agent 解释和结构化结果引用转换为统一消息 DTO。
- [x] 从完整提交记录恢复可恢复的历史解释，生成稳定独立消息 ID。
- [x] 左侧提问目录精确定位消息；相同 task_id 的补参轮次仍可分别跳转。

验收：刷新、切换会话后消息内容与顺序一致；历史图表引用不漂移到最新轮。

验证：历史恢复与 DTO 契约测试；覆盖补参导致 task_id 复用、重复问题、旧解释缺失。

依赖：T03。主要文件：server/routes/sessions.py、server/services/conversations.py、frontend/src/features/sessions/SessionSidebar.tsx、frontend/src/features/chat/Conversation.tsx、tests/test_web_sessions.py。规模：中。

## T05：完成真实单轮分析与模型回复

- [x] POST 问题后创建运行，后台调用 QualityAgent.answer。
- [x] 客户端 submission_id 与现有提交幂等机制统一关联。
- [x] 调整解释长度，使回复能够给出适量短段落与证据。
- [x] 修复多步模式的最终模型解释路径，并配置单次生成预算。
- [x] 持久保存解释正文、来源、引用和模型失败状态。

验收：普通模式和多步模式均能展示真实模型分析；模型不可用时明确显示规则回退；统计数字保持证据约束。

验证：运行／重复提交测试、数字与引用校验回归、真实 Ollama 两种模式冒烟。

依赖：T04。主要文件：server/services/runs.py、server/routes/runs.py、agent/model_adapter.py、agent/workflow.py、agent/graph.py。规模：中；测试代码单独跟随实际改动拆分。

## 检查点 A：真实聊天闭环

- [x] 页面布局与本计划一致。
- [ ] 上传数据 → 创建会话 → 提问 → 模型回复 → 刷新恢复完整可用。
- [x] 预览数据与结构化工具结果可辨认；工具结果来自当前数据源统计。

## T06：接入真实运行事件与提前统计结果

- [x] 将进度回调转换为有序、可重放的 SSE 事件。
- [x] 将部分统计结果转为 statistics.ready 与结果引用。
- [x] 消息内显示阶段状态、耗时和默认折叠的工具详情。
- [x] 实现连接断开提示、EventSource 自动重连和运行快照恢复。

验收：统计结果可在模型文字前展示；重连和多个订阅者不增加模型调用；不显示虚构进度比例。

验证：事件顺序、重复事件、续传、事件过期和多订阅测试；浏览器断网恢复。

依赖：T05。主要文件：server/services/events.py、server/routes/runs.py、frontend/src/lib/run-events.ts、frontend/src/features/chat/RunProgress.tsx、tests/test_web_events.py。规模：中。

## T07：实现停止、冲突与重启中断状态

- [x] 后端实现取消标识和阶段边界检查。
- [x] 模型调用期间显示“正在停止”；返回后阻止后续步骤和正常回复追加。
- [x] 同会话活动运行冲突给出可操作提示。
- [ ] 服务重启会将未结束运行标记为 interrupted 并提示用户；中断轮次的一键重试入口待补。

验收：停止状态由服务端确认；关闭页面不自动取消；重试有独立运行身份，失败历史仍可查看。

验证：排队取消、工具间取消、模型调用中取消、迟到结果、并发提交和服务重启测试。

依赖：T06。主要文件：server/services/runs.py、server/routes/runs.py、agent/workflow.py、frontend/src/features/chat/Composer.tsx、tests/test_web_run_lifecycle.py。规模：中。

## T08：完成右侧结果工作区

- [x] 回复内显示轻量结果入口；右侧按轮次打开趋势、因素、数据和证据。
- [x] 图表接入 ECharts，结果关联分析范围、样本量和数据版本。
- [ ] 因素表支持中文维度和详情；大结果集分页加载待补。
- [ ] 右侧面板支持关闭和窄屏覆盖；桌面可拖拽调整宽度待补。

验收：历史轮次结果与对应条件一致；原始数据量不会直接拖慢聊天首屏。

验证：DTO 与图表数据测试；空数据、长字段、边界值和响应式浏览器检查。

依赖：T06；T07 先完成以保证运行生命周期可用。主要文件：server/routes/results.py、frontend/src/features/results/ResultPanel.tsx、frontend/src/features/results/TrendChart.tsx、frontend/src/features/results/EvidenceView.tsx、frontend/src/features/chat/ArtifactLinks.tsx。规模：中。

## T09：迁移补参、条件继承与长期记忆

- [x] Cpk 缺参卡片继续同一会话中的待补参数任务。
- [x] 明确区分取消待办和停止运行，保留单位确认约束。
- [ ] 每轮显示继承条件与本轮变更，打开范围详情。
- [x] 独立记忆面板提供已确认偏好、规格、来源与适用范围。

验收：补参继续同一任务；明确变更的条件覆盖旧条件；规格不会跨数据版本错误套用。

验证：已有会话／记忆／规格约束回归；浏览器完成一次缺参补充流程。

依赖：T08。主要文件：server/routes/memory.py、server/services/conversations.py、frontend/src/features/chat/PendingInput.tsx、frontend/src/features/memory/MemoryManager.tsx、frontend/src/features/chat/ScopeChanges.tsx。规模：中。

## 检查点 B：运行与上下文

- [ ] 正常、失败、无数据、缺参、取消、重连、重启中断状态全部可辨认。
- [x] 阅读历史时不会被新事件强制拉到底部。
- [x] 模型解释、规则回退、工具证据在界面上有明确标识。

## T10：迁移多文件比较

- [x] 同一问题按数据源独立执行，分别关联结果和运行状态。
- [x] 中间回复按文件组织结论，右侧提供比较表和数据源结果详情。
- [x] 比较历史持久化，并关联各会话的数据版本。
- [x] 单个数据源失败或取消时保留其他来源结果。

验收：来源条件不串用，某一来源取消／失败的状态不会覆盖其他来源；比较历史可刷新恢复。

验证：双文件、部分失败、来源版本变化、比较刷新恢复与结果一致性。

依赖：T09。主要文件：server/services/comparisons.py、server/routes/sessions.py、frontend/src/features/results/ComparisonView.tsx、frontend/src/features/chat/Conversation.tsx、tests/test_web_comparisons.py。规模：中。

## T11：补齐编程 Agent 风格的小交互

- [x] Ctrl+K 搜索、会话重命名、消息复制、失败重试。
- [ ] 提问目录可跳转；新消息提示和跨会话滚动位置恢复待补。
- [ ] 轻量命令菜单、报告 Markdown／结果 CSV 导出已实现；@ 数据引用待补。
- [ ] 历史问题编辑通过分支会话实现，保留原记录。
- [ ] 中文输入法、键盘焦点、减少动画和布局偏好处理。

验收：可见操作全部可用；编辑与重试不会悄悄覆盖历史；原始错误信息不被隐藏。

验证：前端交互测试、导出内容检查和键盘浏览器验收。

依赖：T10。主要文件：frontend/src/features/chat/Composer.tsx、frontend/src/features/chat/MessageActions.tsx、frontend/src/features/sessions/CommandMenu.tsx、server/routes/exports.py、server/services/conversations.py。规模：中；分支若需修改存储，另拆一个子任务。

## T12：启动入口、性能与迁移验收

- [x] 提供一个清晰的新前端启动入口，检查环境、启动 API 并打开页面。
- [x] 开发模式与静态构建发布模式均有文档和健康检查。
- [ ] 对照原有主要业务能力完成迁移矩阵。
- [ ] 记录首屏、首个运行事件、工具统计与模型回复的分段耗时。
- [x] 新入口设为推荐入口；旧 Streamlit 页面和启动器已移除，命令行演示入口保留。

验收：按文档可启动；相关后端回归、前端类型检查与构建通过；桌面和手机尺寸的关键流程通过；默认仅本机访问。

验证：真实 Ollama 冒烟、针对性业务回归、生产构建服务启动、刷新／深链接、至少五次声明环境的性能测量。

依赖：T01–T11。主要文件：start_app.bat、server/main.py、frontend/package.json、README.md、tasks/frontend-redesign/acceptance.md。规模：中。

## 最终完成检查

- [x] 聊天、问题目录、会话历史、结果面板、运行控制均已接入本地后端。
- [ ] 普通模式与多步模式的真实 Ollama 文字分析已验收。
- [x] 上传、Cpk、SPC／异常、记忆、多文件比较已接入；知识查询的独立体验待验收。
- [ ] 验证结果、性能测量环境与尚存限制已记录。
- [ ] 所有依赖版本与启动方式可复现；不存在伪造运行状态或伪造模型流。

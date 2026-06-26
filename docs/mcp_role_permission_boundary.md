# MCP 角色权限与调用边界方案

## 背景

现有自动报价系统已经具备前端报价工作台、表格上传、报价计算、报价保存、历史报价、管理员审批、管理员修正反馈、价格库、知识库和报价单导出等能力。MCP 接入层的目标不是替代这些能力，而是在原系统旁边增加一层受控入口，让 Codex/GPT 可以通过 `mcp-quote-system` 调用已有系统能力。

本阶段只梳理角色、权限、数据范围和工具边界，不新增 MCP 工具，不修改原报价系统逻辑。后续实现必须以“旁路封装、失败隔离、权限清晰”为原则。

## 当前代码依据

本方案基于以下现有文件和行为整理：

- `mcp_server/auth.py`：当前 MCP 权限入口 `require_tool_permission` 只识别 `sales`、`admin`，并对已实现工具统一放行。
- `mcp_server/audit.py`：MCP 审计日志写入 `logs/mcp_audit.jsonl`，JSONL 格式，`ensure_ascii=False`。
- `mcp_server/schemas.py`：当前 MCP 输入校验统一读取 `user_context`，默认 `role=guest`。
- `mcp_server/tools/*.py`：已实现 `quote_calculate`、`price_lookup`、`quote_qa`、`quote_explain`、`quote_patch_preview`、`quote_save`、`quote_export`、`quote_admin`。
- `admin_auth.py`：后台登录角色当前为 `admin` / `user`，其中 `admin` 可访问后台管理能力。
- `sales_auth.py`、`session_quote_context.py`：业务员身份主要来自 `sales_user_id`、`sales_user_name` 和会话 Cookie。
- `quote_upload_storage.py`：原系统报价持久化使用 SQLite，包含 `quotes`、`quote_versions`、`quote_files`、`quote_chat_messages` 等表，并通过 `sales_user_id` 做业务员数据隔离。
- `quote_approval.py`：审批状态标准化为 `pending`、`approved`、`rejected`。
- `server.py`：存在 `/api/my/quotes`、`/api/my/admin-updates`、`/api/quotes/{id}/approval`、`/admin-api/quotes/*` 等原系统接口。
- `static/app.js`：前端已有“我的报价”“管理员修正”“审批状态”“导出 PDF”等用户界面逻辑。

## 角色定义

### sales

普通业务员。对应原系统前台用户和企业微信/本地业务员身份。代码中常见字段是 `sales_user_id`、`sales_user_name`、`sales_user_code`，MCP 中应映射为 `role=sales`。

允许范围：

- 上传或提交自己的报价资料。
- 试算报价。
- 保存自己的报价。
- 查看、预览、导出自己的报价。
- 查询自己的审批状态。
- 查询自己的管理员反馈和修正结果。
- 查询价格或知识库的只读信息。

禁止范围：

- 查看或修改他人报价。
- 审批报价。
- 修改价格库。
- 应用知识库变更。
- 查看全局 MCP 审计日志。
- 执行管理员级删除、冻结、批量管理操作。

### admin

管理员或审批人员。对应 `admin_auth.py` 中后台登录的 `admin`，也对应后台管理接口 `/admin-api/*` 的授权身份。

允许范围：

- 查看后台报价列表。
- 查看待审批或需要处理的报价。
- 审批通过、驳回报价。
- 上传或保存管理员修正反馈。
- 查看业务员报价详情和相关文件。
- 执行受控的报价管理动作。
- 查询价格和知识库只读信息。

限制范围：

- 不建议默认拥有系统级配置权限。
- 不建议默认拥有全局审计日志查看权限。
- 不建议默认拥有价格库写入和知识库批量应用权限，除非业务上确认该管理员兼任系统管理员。

### system_admin

系统管理员。当前 MCP 代码尚未实现 `system_admin` 角色，属于后续建议新增的角色映射。可由环境配置、后台账号类型、企业微信管理员身份或单独的系统管理后台确定。

允许范围：

- 管理 MCP 工具开关和配置。
- 查看 MCP 全局审计日志。
- 管理价格库写入。
- 应用知识库变更。
- 管理用户和角色映射。
- 执行系统级诊断、数据修复和权限调整。

限制范围：

- 系统管理员操作也必须审计。
- 涉及删除、批量覆盖、知识库应用、价格更新的操作应具备二次确认或审批链。

### 现有命名映射建议

| 当前代码命名 | 建议 MCP 角色 | 说明 |
|---|---|---|
| `sales_user_id` / `sales_user_name` / `sales_user_code` | `sales` | 原系统业务员身份，不应只用短会话 `session_id` 作为归属依据。 |
| `admin_auth.ROLE_ADMIN == "admin"` | `admin` | 后台管理员或审批人员。 |
| `admin_auth.ROLE_USER == "user"` | `sales` 或内部只读用户 | 当前后台 `user` 不等同于 MCP `system_admin`，需要明确映射后再开放。 |
| `guest` | 无权限或极少数公开只读 | MCP 默认角色，不能调用报价、保存、导出、审批等工具。 |
| `system_admin` | `system_admin` | 当前未实现，建议作为新增角色。 |

## MCP user_context 建议字段

MCP 调用必须带 `user_context`。缺省时只能视为 `guest`，不能默认提升为业务员或管理员。

建议结构：

```json
{
  "user_id": "sales_001",
  "user_name": "张三",
  "role": "sales",
  "session_id": "sess_001",
  "sales_user_id": "local:20",
  "sales_user_name": "张三",
  "sales_user_code": "20",
  "source": "codex",
  "request_id": "req_xxx"
}
```

字段说明：

- `role`：必需，允许值建议为 `sales`、`admin`、`system_admin`。缺省按 `guest` 处理。
- `user_id`：MCP 调用方身份，用于审计和工具权限。
- `session_id`：会话链路追踪字段，不应用作长期报价归属。
- `sales_user_id`：业务员数据归属字段。sales 查询、导出、反馈拉取必须按该字段过滤。
- `sales_user_name` / `sales_user_code`：展示和辅助映射字段。
- `source`：建议标记 `codex`、`web_frontend`、`automation` 等来源。
- `request_id`：建议用于串联审计、错误排查和幂等控制。

## 数据范围原则

### sales 数据范围

sales 只能访问自己名下报价。原系统 `quote_upload_storage.sales_user_can_access_quote()` 和 `list_my_quotes_for_sales_user()` 已体现该原则：报价必须绑定 `sales_user_id`，且未被业务员侧隐藏。

MCP 工具后续接入原系统历史、审批、反馈时，应继承该规则：

- 查询历史报价时，只返回 `sales_user_id == user_context.sales_user_id` 的报价。
- 查询报价详情时，必须校验 `sales_user_can_access_quote(quote_uid, sales_user_id)`。
- 导出报价单时，只能导出自己可访问的报价。
- 查询审批状态时，只能查询自己报价的审批状态。
- 查询反馈列表时，只能查询自己的管理员反馈。

### admin 数据范围

admin 可以访问后台管理所需的报价数据。当前 `/admin-api/quotes`、`get_saved_quote_admin_bundle()`、`update_saved_quote_approval()` 等能力体现管理员后台视角。

建议边界：

- 默认可查看所有报价或后台列表范围内报价。
- 如果后续有“分配审批人”字段，则 admin 应只看分配给自己或所在组的报价。
- admin 可审批、驳回、上传修正反馈，但不默认拥有价格库写入和系统审计查看权限。

### system_admin 数据范围

system_admin 可查看全局数据和审计日志，可执行系统配置、价格库、知识库级操作。该角色必须最小化人数，并对所有写操作保留审计。

## 角色 x MCP 工具权限表

下表是后续规划权限，不代表当前所有工具已实现。

| 工具 | sales | admin | system_admin | 数据范围 | 备注 |
|---|---:|---:|---:|---|---|
| `quote_from_file` | 是 | 是 | 是 | sales 仅自己的上传和报价；admin/system_admin 按后台权限 | 规划工具。应复用原上传/解析/报价流程，不重写 Excel 解析。 |
| `quote_calculate` | 是 | 是 | 是 | 输入 payload 试算，不落历史 | 已实现。只做 preview，不保存正式报价。 |
| `quote_save` | 是 | 是 | 是 | sales 只能保存到自己名下；admin 可代保存需标注来源 | 已实现但当前写 `data/mcp_saved_quotes.jsonl`，后续若进入原历史需桥接 SQLite。 |
| `quote_preview` | 是 | 是 | 是 | sales 仅自己的报价；admin/system_admin 按后台权限 | 规划工具。应返回原系统报价单预览 URL。 |
| `quote_export` | 是 | 是 | 是 | sales 仅自己的报价；admin/system_admin 按后台权限 | 已实现简版 PDF 导出；后续建议复用原系统模板/预览页。 |
| `quote_approval_status` | 是 | 是 | 是 | sales 仅自己的报价；admin/system_admin 按后台权限 | 规划工具。应读取原审批状态 `pending/approved/rejected`。 |
| `quote_feedback_inbox` | 是 | 是 | 是 | sales 仅自己的反馈；admin 可看处理范围；system_admin 全局 | 规划工具。用于 Codex/GPT 拉取管理员反馈列表。 |
| `quote_feedback_detail` | 是 | 是 | 是 | sales 仅自己的反馈详情；admin/system_admin 按权限 | 规划工具。应包含审批意见、修正说明、文件引用、必要 diff。 |
| `quote_feedback_mark_read` | 是 | 是 | 是 | sales 只能标记自己的反馈；admin/system_admin 按权限 | 规划工具。写操作，需审计。 |
| `quote_admin` | 否，除只读 `view_quote` 可按需开放 | 是 | 是 | admin/system_admin 按后台权限 | 已实现。当前 sales 可 `view_quote`，后续要加归属校验。 |
| `price_lookup` | 是 | 是 | 是 | 只读价格查询 | 已实现，只读。 |
| `price_update` | 否 | 否或需单独授权 | 是 | 全局价格库 | 规划工具。高风险写操作，建议 system_admin 专属。 |
| `knowledge_apply` | 否 | 否或需单独授权 | 是 | 全局知识库 | 规划工具。高风险写操作，建议 system_admin 专属。 |
| `mcp_audit_view` | 否 | 否或只看自己操作 | 是 | MCP 审计日志 | 规划工具。默认 system_admin 专属。 |

## 每个 MCP 工具调用边界

### quote_from_file

能做：

- 接收 Codex/GPT 传入的文件路径、上传来源和用户上下文。
- 调用原系统已有上传、解析、报价和持久化流程。
- 生成可进入历史报价的记录。

不能做：

- 不能重写 Excel/CSV/图片解析规则。
- 不能绕过原系统报价公式。
- 不能让 GPT 自己计算价格。
- 不能直接覆盖原上传文件或历史报价。

写数据：是，可能写上传文件、报价历史、版本、附件记录。

审计：必须。

错误隔离：必须。失败只返回 MCP 错误，不影响原前端上传报价流程。

### quote_calculate

能做：

- 对结构化 `payload` 调用现有报价引擎试算。
- 返回预览报价结果。

不能做：

- 不能保存正式报价。
- 不能修改价格库。
- 不能调用大模型计算价格。
- 不能复制或改写 `quote_engine.py` 报价公式。

写数据：不写业务数据，只写 MCP 审计日志。

审计：必须。

错误隔离：必须。

### quote_save

能做：

- 保存已确认的 `quote_result`。
- 生成 `quote_id`、锁定快照，并供后续导出或审批查询使用。

不能做：

- 不能保存未确认或由 GPT 自己生成金额的报价。
- 不能破坏原系统历史报价结构。
- 不能覆盖旧报价记录。

写数据：是。

审计：必须。

现状限制：

- 当前 MCP `quote_save` 写入 `data/mcp_saved_quotes.jsonl`，不等同于原系统 SQLite 历史报价。后续若要求“原历史报价可见”，应通过原持久化服务或桥接函数写入 `quotes` / `quote_versions` 等表。

错误隔离：必须。

### quote_preview

能做：

- 根据 `quote_id` 或 `quote_series_uid` 返回原系统报价单预览 URL。
- 复用原系统报价单 DOM、模板和数据填充逻辑。

不能做：

- 不能由 Codex/GPT 临时生成一套新的报价单 HTML。
- 不能改变原报价单填写页行为。
- 不能接管原前端按钮。

写数据：通常只读；如生成一次性预览 token，可写轻量临时记录。

审计：建议必须，至少记录访问人、报价 ID、成功/失败。

错误隔离：必须。

### quote_export

能做：

- 对已保存、已授权访问的报价导出 PDF/HTML/XLSX。
- 后续应优先通过原系统预览页渲染后导出，保证报价单视觉一致。

不能做：

- 不能让 Codex/GPT 自己排版报价单。
- 不能重写或替换原报价单模板。
- 不能破坏原 PDF 导出按钮。
- 不能重新计算报价金额。

写数据：是，写导出文件；可能写导出记录。

审计：必须。

现状限制：

- 当前 MCP `quote_export` 从 `data/mcp_saved_quotes.jsonl` 读取，并用后端简版 PDF 生成。它可作为 MCP 隔离导出入口，但不应声明为原系统报价单模板导出。

错误隔离：必须。PDF 生成失败只能返回 `ok=false`，不能影响原系统页面导出。

### quote_approval_status

能做：

- 查询某个报价的审批状态、审批备注、审批人展示名和更新时间。
- 对 sales 返回公开审批快照。

不能做：

- 不能修改审批状态。
- 不能向 sales 暴露内部版本 ID、后台账号、敏感操作记录。

写数据：否。

审计：必须。

错误隔离：必须。

### quote_feedback_inbox

能做：

- 查询当前用户可见的管理员反馈、修正、审批通知列表。
- 支持 `unread_only`、`limit`、状态筛选。

不能做：

- sales 不能查看他人的反馈。
- 不能把后台全量修正记录直接暴露给 Codex/GPT。

写数据：否。

审计：必须。

错误隔离：必须。

### quote_feedback_detail

能做：

- 查询单条管理员反馈详情。
- 返回修正说明、审批意见、问题类型、修正后报价摘要、可下载文件引用等。

不能做：

- 不能泄露无权限报价。
- 不能返回数据库路径、内部 token、后台 Cookie 等敏感字段。

写数据：否；如果打开详情自动标记 viewed，则应明确作为写操作。

审计：必须。

错误隔离：必须。

### quote_feedback_mark_read

能做：

- 将当前业务员自己的反馈标记为已读或已处理。

不能做：

- 不能批量标记他人反馈。
- 不能修改反馈内容或审批状态。

写数据：是。

审计：必须。

错误隔离：必须。

### quote_admin

能做：

- 管理员审批、驳回、冻结、解冻、标记导出、查看报价摘要。

不能做：

- sales 不能执行审批/驳回/冻结/价格规则更新。
- 不能绕过原后台权限。
- 不应把多个高风险系统管理动作长期塞进一个泛化工具。

写数据：视 action 而定。审批、驳回、冻结、价格规则更新均为写操作。

审计：必须。

现状限制：

- 当前 MCP `quote_admin` 主要操作 `data/mcp_saved_quotes.jsonl` 和 `data/mcp_price_rules_admin.jsonl`。后续若要操作原审批流程，应调用原系统 `update_saved_quote_approval()` 等服务函数，并保持原后台行为不变。

错误隔离：必须。

### price_lookup

能做：

- 从价格库只读查询材料、规格和价格候选。

不能做：

- 不能修改价格库。
- 不能自动学习或自动写入价格。

写数据：不写业务数据，只写 MCP 审计日志。

审计：必须。

错误隔离：必须。

### price_update

能做：

- 系统管理员受控更新价格库。

不能做：

- sales 禁止调用。
- 普通 admin 默认不建议调用。
- 不能绕过价格审核、备份和回滚机制。

写数据：是，高风险。

审计：必须，且建议记录变更前后摘要、操作者、来源、审批单号。

错误隔离：必须。

### knowledge_apply

能做：

- 系统管理员将已审核知识变更应用到知识库。

不能做：

- 不能让 Codex/GPT 未经确认直接写知识库。
- 不能批量覆盖知识库而无备份。

写数据：是，高风险。

审计：必须。

错误隔离：必须。

### mcp_audit_view

能做：

- 查询 MCP 审计日志。
- 支持按用户、工具、时间、成功/失败过滤。

不能做：

- sales 默认不能查看。
- admin 默认不建议查看全局日志，可按需要只看自己相关操作。
- 不能返回敏感 payload、token、Cookie、数据库路径。

写数据：否。

审计：建议记录查询审计日志这一行为。

错误隔离：必须。

## 审计日志要求

所有 MCP 工具调用，无论成功失败，都应写审计日志。

基础字段建议：

- `timestamp`
- `tool`
- `mode`
- `user_id`
- `user_name`
- `role`
- `session_id`
- `sales_user_id`
- `request_id`
- `quote_id`
- `quote_series_uid`
- `action`
- `success`
- `error`
- `source`

字段原则：

- 审计日志保留操作摘要，不记录完整报价大对象、完整上传文件内容、Cookie、token、密钥或数据库路径。
- 失败也要记录，尤其是权限失败、参数校验失败、文件生成失败、原服务调用失败。
- `ensure_ascii=False`，便于中文排查。
- 日志写入失败不能导致原系统页面功能失败；MCP 工具内部可尽量吞掉审计写入异常并返回主操作结果。

## 错误隔离要求

MCP 是旁路接入层。所有 MCP 工具失败时，应只影响该次 MCP 调用。

统一失败返回建议：

```json
{
  "ok": false,
  "tool": "quote_export",
  "error": "导出失败原因",
  "request_id": "req_xxx"
}
```

隔离要求：

- MCP 参数错误不能影响原前端上传报价。
- MCP 权限失败不能影响原业务员页面。
- MCP 导出失败不能影响原报价单填写和 PDF 导出按钮。
- MCP 保存失败不能破坏原历史报价数据库。
- MCP 审批查询失败不能改变审批状态。
- MCP 管理动作失败不能部分写入。高风险写操作应尽量具备事务或回滚。

## 不影响原系统的硬边界

后续 MCP 实现必须遵守：

- 不修改 `quote_engine.py` 报价公式。
- 不重构原 `server.py` 的正常报价流程。
- 不改坏原前端上传表格、生成报价、查看历史、继续报价、生成报价单、导出 PDF 的流程。
- 不替换原报价单模板。
- 不接管原前端导出按钮。
- 不改变原 API 返回结构导致旧前端报错。
- 不绕过原后台管理员权限。
- 不覆盖原历史报价、附件、审批、管理员反馈数据。
- 新 MCP 路由或工具只能作为新增入口；即使复用原服务函数，也必须保持旧调用方参数和返回值兼容。

## 审批反馈给 Codex/GPT 的方式

Codex/GPT 不是常驻前端，也不是一直在线的浏览器客户端。后端默认不能像推送网页通知一样主动把审批结果推给 Codex/GPT。

推荐方式是 MCP 查询：

- 用户问“这个报价审批过了吗？”时，Codex/GPT 调用 `quote_approval_status`。
- 用户问“管理员有没有反馈？”时，Codex/GPT 调用 `quote_feedback_inbox`。
- 用户要看某条反馈详情时，Codex/GPT 调用 `quote_feedback_detail`。
- 用户确认已处理反馈时，Codex/GPT 调用 `quote_feedback_mark_read`。

如果未来需要主动提醒，应另行设计企业微信通知、邮件、Webhook、定时任务或 Codex 自动化唤醒。这不属于第一阶段 MCP 基础封装范围。

## 现有问题和风险记录

1. 当前 MCP 权限模型只有 `sales/admin`，尚无 `system_admin`。
2. 当前 `require_tool_permission` 对多个工具采用统一放行，缺少按工具、按 action、按数据归属的细粒度权限。
3. 当前 `quote_admin` 内部允许 `sales` 执行 `view_quote`，但后续必须补报价归属校验，否则有越权查看风险。
4. 当前 MCP `quote_save/quote_export/quote_admin` 使用 JSONL 独立存储，不等于原系统 SQLite 报价历史、审批和反馈体系。
5. 当前 MCP `quote_export` 是后端简版 PDF，不是原系统报价单模板导出。后续若要求视觉一致，应通过 `quote_preview` 和浏览器渲染原模板导出。
6. 当前审计日志是 JSONL 文件，适合第一阶段，但后续若进入生产，应考虑查询、归档、脱敏、权限查看和异常告警。
7. 当前工具输入中的 `user_context` 尚未统一要求 `sales_user_id`，后续涉及历史、导出、审批、反馈查询时必须补齐。

## 后续实施建议

### 第一阶段：权限模型固化

- 扩展 `mcp_server/auth.py`，支持 `system_admin`。
- 增加工具级、action 级权限表。
- 明确 `user_context` 必填字段和角色映射。
- 为数据归属校验预留统一函数，例如 `require_quote_access(user_context, quote_uid, action)`。

### 第二阶段：原系统历史和 MCP 保存桥接

- 让 `quote_save` 可选调用原系统持久化服务，生成 `quote_series_uid`。
- 保留当前 JSONL 作为 MCP 试验存储或迁移兼容层。
- 确保 sales 保存后能在 `/api/my/quotes` 看见自己的记录。

### 第三阶段：quote_preview 和 quote_export 一致性

- 新增 `quote_preview`，返回原系统报价单预览 URL。
- 改造 MCP `quote_export` 为复用原预览页模板导出，而不是让 Codex/GPT 或 Python 另起模板。
- 保持原前端导出按钮不变。

### 第四阶段：审批和管理员反馈查询

- 新增 `quote_approval_status`，只读查询审批状态。
- 新增 `quote_feedback_inbox`、`quote_feedback_detail`、`quote_feedback_mark_read`。
- 全部按 `sales_user_id` 做业务员侧隔离。

### 第五阶段：系统管理员工具

- 在明确 `system_admin` 后再考虑 `price_update`、`knowledge_apply`、`mcp_audit_view`。
- 高风险写操作必须有审计、备份、回滚和二次确认。

## 第一阶段验收口径

第一阶段只交付本方案文档。符合验收的标准是：

- 明确角色：`sales`、`admin`、`system_admin`。
- 明确角色映射和当前代码命名差异。
- 明确 sales/admin/system_admin 的数据范围。
- 明确候选 MCP 工具权限表。
- 明确每个工具能做什么、不能做什么、是否写数据、是否审计、是否错误隔离。
- 明确 Codex/GPT 通过查询型 MCP 工具拉取审批反馈。
- 明确 MCP 不能影响原报价系统。
- 不修改原系统业务代码。

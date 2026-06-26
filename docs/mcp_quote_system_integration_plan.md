# 自动报价系统 MCP 接入层思路文档

## 1. 核心结论

MCP 不应该替代现有报价系统，也不应该重写报价前端、报价引擎、审批后台或报价单模板。

正确方向是：保留原系统，在原系统旁边新增一层 MCP 接入层，让 Codex/GPT 通过 MCP 调用系统已有能力。

可以理解为：

```text
原报价系统 = 主业务系统
MCP 接入层 = 给 Codex/GPT 使用的旁路遥控器
```

原来的网页上传、自动报价、历史记录、审批、报价单填写、PDF 导出都继续保持不变。MCP 只新增调用入口。

## 2. 为什么不能只封装 quote_calculate

如果只封装报价计算，会出现业务链路断裂：

```text
Codex/GPT 能算价
但原系统不一定知道这次表格上传
历史记录不一定能查到
报价单导出不一定能使用原模板
审批反馈不一定能回到 Codex/GPT
```

完整业务链路应该是：

```text
用户需求 / 表格 / 图片
  -> Codex/GPT 调 MCP
  -> quote_from_file 或 quote_calculate 得到报价
  -> quote_save 保存报价结果
  -> quote_preview 查看系统原生报价单预览
  -> quote_export 导出系统原生 PDF/HTML/XLSX
  -> quote_approval_status / quote_feedback_inbox 查询审批反馈
```

## 3. 系统边界

### 3.1 原系统继续负责

- 表格上传与解析
- 图片识别与报价信息提取
- 报价计算规则
- 价格库和知识库
- 报价历史记录
- 管理员审批
- 管理员修正反馈
- 报价单模板
- PDF/HTML/XLSX 导出
- 原前端页面交互

### 3.2 MCP 接入层负责

- 暴露一组受权限控制的工具
- 接收 Codex/GPT 的结构化调用
- 调用原系统已有服务
- 返回结构化结果、文件路径或预览链接
- 写 MCP 审计日志
- 在失败时返回 MCP 错误，不影响原系统

MCP 不负责重新设计报价单样式，也不负责绕过原系统权限。

## 4. 推荐 MCP 工具设计

### 4.1 quote_from_file

作用：让 Codex/GPT 把用户给的 Excel/CSV/图片真正交给原系统处理。

输入示例：

```json
{
  "user_context": {
    "user_id": "sales_001",
    "role": "sales",
    "session_id": "sess_001"
  },
  "query": {
    "file_path": "D:/测试数据/B260168--报价资料.xlsx",
    "source": "codex_upload",
    "save_original": true,
    "auto_save_quote": true
  }
}
```

输出示例：

```json
{
  "ok": true,
  "tool": "quote_from_file",
  "quote_id": "Q20260626-001",
  "quote_series_uid": "series_xxx",
  "sheet_original_name": "B260168--报价资料.xlsx",
  "quote_result": {},
  "source": "mcp_file_upload"
}
```

实现原则：不要重写 Excel 解析逻辑，应该调用原系统现有的上传、解析、报价流程。

### 4.2 quote_calculate

作用：对已经结构化的 payload 进行报价试算。

适用场景：

- Codex/GPT 已经有结构化物料和费用字段
- 只需要试算，不一定保存到历史记录
- 用户想临时比较不同数量、利润率或费用口径

### 4.3 quote_save

作用：保存 quote_calculate 或 quote_from_file 得到的 quote_result，生成 quote_id / quote_series_uid。

要求：

- 保存结果必须能被 quote_export、quote_preview、quote_approval_status 查询到
- 不要破坏原系统历史报价结构
- MCP 来源可以标记为 `mcp_file_upload` 或 `mcp_calculate`

### 4.4 quote_preview

作用：返回系统原生报价单预览 URL。

输出示例：

```json
{
  "ok": true,
  "quote_id": "Q20260626-001",
  "quote_series_uid": "series_xxx",
  "preview_url": "http://127.0.0.1:8776/quote-preview/series_xxx"
}
```

要求：

- 预览页面必须复用系统原生报价单模板
- 不要由 Codex/GPT 临时生成一个新的 HTML

### 4.5 quote_export

作用：调用系统原生报价单模板导出 PDF / HTML / XLSX。

输入示例：

```json
{
  "query": {
    "quote_id": "Q20260626-001",
    "quote_series_uid": "series_xxx",
    "format": "pdf",
    "currency": "rmb",
    "language": "cn",
    "template": "system_default"
  }
}
```

输出示例：

```json
{
  "ok": true,
  "tool": "quote_export",
  "mode": "export",
  "quote_id": "Q20260626-001",
  "quote_series_uid": "series_xxx",
  "format": "pdf",
  "file_path": "D:/完整版自动报价/outputs/mcp_exports/Q20260626-001.pdf",
  "url": "http://127.0.0.1:8776/exports/mcp/Q20260626-001.pdf",
  "template": "system_default"
}
```

重要要求：

- quote_export 不能让 Codex/GPT 自己排版报价单
- 样式必须由系统模板决定
- 如果导出 PDF，优先用浏览器渲染系统原生报价单页面后导出
- 不建议用 Python 手写 PDF 去复刻前端报价单

### 4.6 quote_approval_status

作用：Codex/GPT 查询某个报价的审批状态。

输出示例：

```json
{
  "ok": true,
  "quote_series_uid": "series_xxx",
  "approval_status": "pending",
  "approval_comment": "",
  "updated_at": "2026-06-26 10:30:00"
}
```

审批通过示例：

```json
{
  "ok": true,
  "quote_series_uid": "series_xxx",
  "approval_status": "approved",
  "approval_comment": "可以发客户",
  "approved_by": "admin_001",
  "updated_at": "2026-06-26 10:45:00"
}
```

### 4.7 quote_feedback_inbox

作用：Codex/GPT 查询当前业务员的管理员反馈、BOM 修正、审批通知。

输入示例：

```json
{
  "query": {
    "user_id": "sales_001",
    "unread_only": true,
    "limit": 20
  }
}
```

输出示例：

```json
{
  "ok": true,
  "items": [
    {
      "update_id": "upd_001",
      "quote_series_uid": "series_xxx",
      "type": "admin_correction",
      "status": "unread",
      "message": "管理员修正了包边带用量",
      "created_at": "2026-06-26 10:31:00"
    }
  ]
}
```

### 4.8 quote_feedback_detail

作用：查看某条管理员反馈的详情和 diff。

### 4.9 quote_feedback_mark_read

作用：标记反馈已读，避免 Codex/GPT 重复提醒。

### 4.10 quote_admin

作用：管理员审批、驳回、冻结、查看报价等。

该工具只允许 admin / system_admin 角色调用。

## 5. 角色与权限设计

建议先按三类角色设计。

### 5.1 sales / user

允许：

- 上传表格/图片报价
- 查看自己的报价
- 保存自己的报价
- 导出自己的报价单
- 查询自己的审批状态
- 查询自己的管理员反馈

不允许：

- 审批报价
- 修改他人报价
- 修改价格库
- 修改知识库
- 查看 MCP 全局审计日志

### 5.2 admin

允许：

- 查看待审批报价
- 审批通过/驳回
- 查看业务员报价
- 发送管理员修正反馈
- 查看反馈处理状态

不建议允许：

- 修改系统级 MCP 配置
- 批量改知识库
- 查看所有敏感审计日志

### 5.3 system_admin

允许：

- 管理价格库
- 管理知识库
- 管理用户权限
- 查看 MCP 审计日志
- 开启/关闭 MCP 工具
- 调整系统配置

### 5.4 工具权限表

```text
工具                       sales   admin   system_admin
quote_from_file             yes     yes     yes
quote_calculate             yes     yes     yes
quote_save                  yes     yes     yes
quote_preview               yes     yes     yes
quote_export                yes     yes     yes
quote_approval_status       yes     yes     yes
quote_feedback_inbox        yes     yes     yes
quote_feedback_detail       yes     yes     yes
quote_feedback_mark_read    yes     yes     yes
quote_admin                 no      yes     yes
price_lookup                yes     yes     yes
price_update                no      no      yes
knowledge_apply             no      no      yes
mcp_audit_view              no      no      yes
```

## 6. Codex/GPT 如何接收审批结果

Codex/GPT 不是你的系统前端，也不是常驻在线的浏览器客户端。

所以后端审批完成后，默认不能像推送给网页前端一样主动推给 Codex/GPT。

推荐做法是 MCP 查询：

```text
用户问：这个报价审批过了吗？
  -> Codex/GPT 调 quote_approval_status
  -> 返回审批状态

用户问：管理员有没有反馈？
  -> Codex/GPT 调 quote_feedback_inbox
  -> 返回反馈列表
```

如果未来要主动提醒，需要另外设计：

- 企业微信通知
- 邮件
- Webhook
- 定时任务
- Codex 自动化唤醒

但这不是 MCP 基础封装的第一阶段重点。

## 7. 报价单导出一致性方案

问题：Codex/GPT 自己生成 PDF/HTML，效果和原系统报价单不一致。

解决：

```text
不要让 Codex/GPT 自己生成报价单
让 quote_export 调系统原生报价单模板
```

推荐导出流程：

```text
quote_save 得到 quote_series_uid
  -> quote_preview 返回系统原生预览 URL
  -> quote_export 打开系统原生预览页面
  -> 浏览器渲染 HTML
  -> page.pdf() 导出 PDF
  -> 返回 file_path / url
```

原则：

- HTML 模板是唯一视觉源
- PDF 是 HTML 的打印结果
- 不要复制一套 PDF 样式
- 不要让大模型决定字体、表格宽度、布局

## 8. 对原系统的影响控制

MCP 封装必须作为旁路能力实现。

允许：

- 新增 MCP 工具
- 新增导出服务
- 新增预览路由
- 新增 `outputs/mcp_exports` 输出目录
- 新增 audit log
- 新增测试

禁止：

- 替换原报价系统前端
- 破坏原上传报价流程
- 破坏原历史报价
- 破坏原报价单填写页
- 破坏原 PDF 导出按钮
- 修改旧接口返回结构导致旧前端报错
- 覆盖原系统导出的文件
- 绕过现有权限

MCP 调用失败时，只能影响 MCP 返回值：

```json
{
  "ok": false,
  "error": "导出失败原因"
}
```

不能影响原系统页面功能。

## 9. 推荐实施阶段

### 阶段一：梳理权限和现有流程

- 梳理当前系统角色
- 梳理报价保存结构
- 梳理 quote_id / quote_series_uid 关系
- 梳理原报价单导出入口
- 梳理管理员审批反馈数据结构

### 阶段二：完善 quote_export 和 quote_preview

- 先实现 html 预览
- 再实现 PDF 导出
- 确保复用系统原模板

### 阶段三：新增 quote_from_file

- 让 Codex/GPT 给出的表格/图片真正进入原报价系统
- 保存原始附件
- 生成历史报价记录

### 阶段四：新增审批反馈查询

- quote_approval_status
- quote_feedback_inbox
- quote_feedback_detail
- quote_feedback_mark_read

### 阶段五：完善审计和开关

- 所有 MCP 调用写审计日志
- 增加 MCP 工具开关
- 增加错误隔离

## 10. 测试建议

至少覆盖：

- sales 可以 quote_from_file / quote_export 自己的报价
- sales 不能调用 quote_admin
- admin 可以审批报价
- system_admin 可以查看 MCP 审计日志
- quote_export 找不到 quote_id 时返回清晰错误
- quote_export 失败不影响原系统导出按钮
- quote_preview 返回系统原生预览 URL
- quote_save 后 quote_export 能找到同一个 quote_result
- quote_feedback_inbox 只返回当前用户可见反馈
- 原有报价系统测试仍通过

## 11. 最终验收标准

- 原报价系统功能不受影响
- Codex/GPT 可以通过 MCP 上传/计算/保存/预览/导出报价
- MCP 导出的报价单来自系统原生模板
- 审批反馈可以通过 MCP 查询
- 工具权限清晰
- 所有 MCP 调用有审计
- MCP 失败不会破坏原系统


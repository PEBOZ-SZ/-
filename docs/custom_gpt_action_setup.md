# Custom GPT Action Setup

## 前置条件

- 自动报价服务需要公网 HTTPS 域名；当前生产域名统一使用 `https://weilai-pxj.com`。
- 服务端必须设置环境变量 `GPT_ACTION_TOKEN`。
- `GPT_ACTION_TOKEN` 建议使用高强度随机值，不要写入代码仓库。
- Custom GPT Actions 使用 `docs/gpt_action_openapi.yaml` 中的安全接口，包括 `/api/quote/import` 和 `/gpt/quote-agent`；不要额外配置后台、管理、审批处理接口。

## 服务端配置

在部署环境中设置：

```bash
GPT_ACTION_TOKEN=replace-with-a-long-random-token
```

重启自动报价服务后，确认公网域名能访问：

```text
https://weilai-pxj.com/gpt/quote-agent
https://weilai-pxj.com/api/quote/import
```

该接口只接受 `POST` 和 JSON object。

## Custom GPT Actions 配置

1. 打开 Custom GPT 的 Configure。
2. 在 Actions 中新增一个 Action。
3. Authentication 选择 API Key。
4. Auth Type 选择 Bearer。
5. Token 填写服务端同一个 `GPT_ACTION_TOKEN` 值。
6. Schema 粘贴 `docs/gpt_action_openapi.yaml` 的全部内容。
7. 确认 schema 里的 `servers.url` 是 `https://weilai-pxj.com`。
8. 保存 Action。

## Custom GPT Instructions

将 `docs/custom_gpt_instructions.md` 中代码块内的内容复制到 Custom GPT Instructions。

## 建议测试用例

在 Custom GPT 中按顺序测试：

1. 上传或提供一份报价资料，让 GPT 计算并调用 `importQuoteSheet` 生成系统报价单预览/下载链接。
2. 输入：`数量改300`
   - 期望：调用 quoteAgent，返回报价草稿已更新，并由系统重新计算。
3. 输入：`PU料按6.5`
   - 期望：调用 quoteAgent，修改材料单价，并由系统重新计算。
4. 输入：`重新计算`
   - 期望：调用 quoteAgent，通过后端报价引擎重新计算。
5. 输入：`确认保存`
   - 期望：如果无 missing_fields / risk_flags，则保存并进入待处理状态。
6. 构造仍有风险的草稿后输入：`确认保存`
   - 期望：返回 clarify，说明风险未处理，不能保存正式报价。

## 第一条消息示例

可以在 Custom GPT 里先发：

```text
帮我根据这份报价资料创建报价草稿，session_id 用 gpt-demo-001。先不要正式保存。
```

如果已有系统生成的 `payload` 或 `quote_result`，Custom GPT 应调用 `quoteAgent` 并传入这些对象。

## 审计日志

GPT Action 调用会写入：

```text
logs/gpt_action_audit.jsonl
```

每行记录：

- timestamp
- request_id
- session_id
- message_summary
- type
- ok
- missing_fields_count
- risk_flags_count
- quote_id
- saved

日志不会记录完整 `quote_result`、完整材料明细或 token。日志写入失败不会影响主流程。

## 常见问题

### 401 token 错误

- 检查 Custom GPT Action 的 Bearer token 是否与服务端 `GPT_ACTION_TOKEN` 完全一致。
- 检查请求头是否为 `Authorization: Bearer <token>`。
- 检查服务端是否已重启并加载新环境变量。

### Schema 导入失败

- 确认粘贴的是完整 `docs/gpt_action_openapi.yaml` 内容。
- 确认 `servers.url` 已替换为公网 HTTPS 域名。
- 确认 YAML 缩进未被破坏。

### GPT 没调用 Action 而自己回答

- 检查 Instructions 是否包含“导出/下载报价单必须调用系统报价单 Action，不允许本地生成 Excel/PDF/HTML”。
- 检查 schema 中有 `operationId: importQuoteSheet` 和 `operationId: quoteAgent`。
- 如果系统报价单接口失败，GPT 应提示失败并重试或先保存记录，不能给用户生成临时 Excel。

### 系统返回 clarify

- 说明报价草稿仍缺信息或存在风险。
- 按 assistant_message 补充材料、用量、单价、BOM 是否参与报价等信息。
- 不要要求 GPT 跳过风险保存。

### 保存失败

- 确认草稿已有有效 `quote_id`。
- 先输入 `重新计算`，让系统生成最新试算结果。
- 确认 missing_fields / risk_flags 已清空。
- 检查服务端日志和 `logs/gpt_action_audit.jsonl` 中对应 request_id。


# Custom GPT Live Checklist

这份清单用于 Custom GPT Actions 真实接入前的部署联调。不要把真实 token 写入文档、代码或截图。

## A. 服务端检查

1. 设置环境变量：

```bash
GPT_ACTION_TOKEN=replace-with-a-long-random-token
QUOTE_SERVER_HOST=0.0.0.0
QUOTE_SERVER_PORT=8776
QUOTE_PUBLIC_BASE_URL=https://weilai-pxj.com
```

2. 启动自动报价服务。

```bash
python server.py
```

如果使用平台进程管理器或容器部署，以线上实际启动方式为准。

3. 确认公网 HTTPS 可访问：

```bash
curl -i "$QUOTE_PUBLIC_BASE_URL/gpt/quote-agent"
```

预期：`405`，表示路径可达但必须使用 POST。

4. 确认 OpenAPI schema 中的 `servers.url` 已设置为生产公网 HTTPS 域名：

```text
https://weilai-pxj.com
```

该值应与 `$QUOTE_PUBLIC_BASE_URL` 保持一致。

5. 确认 `logs/gpt_action_audit.jsonl` 只记录摘要字段，不记录 token、完整 `quote_result` 或 `detail_rows`。

## B. curl 测试命令

以下命令使用占位符，不要直接写真实 token。

### 1. 无 Authorization，应返回 401

```bash
curl -i -X POST "$QUOTE_PUBLIC_BASE_URL/gpt/quote-agent" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"gpt-demo-001","message":"数量改300"}'
```

### 2. 错 token，应返回 401

```bash
curl -i -X POST "$QUOTE_PUBLIC_BASE_URL/gpt/quote-agent" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer wrong-token" \
  -d '{"session_id":"gpt-demo-001","message":"数量改300"}'
```

### 3. 正确 token + 数量改300，应返回 quote_updated 或 clarify

```bash
curl -i -X POST "$QUOTE_PUBLIC_BASE_URL/gpt/quote-agent" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GPT_ACTION_TOKEN" \
  -d '{"session_id":"gpt-demo-001","message":"数量改300","payload":{"product_name":"测试包","quantities":[500],"items":[{"name":"PU料","usage":"0.5平方","unit_price":"6元","amount":3}]}}'
```

### 4. 正确 token + 重新计算

```bash
curl -i -X POST "$QUOTE_PUBLIC_BASE_URL/gpt/quote-agent" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GPT_ACTION_TOKEN" \
  -d '{"session_id":"gpt-demo-001","message":"重新计算"}'
```

### 5. 正确 token + 确认保存

```bash
curl -i -X POST "$QUOTE_PUBLIC_BASE_URL/gpt/quote-agent" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GPT_ACTION_TOKEN" \
  -d '{"session_id":"gpt-demo-001","message":"确认保存"}'
```

### 6. 正确 token + 未知 GPT 路径，应返回 404

```bash
curl -i -X POST "$QUOTE_PUBLIC_BASE_URL/gpt/unknown" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GPT_ACTION_TOKEN" \
  -d '{"session_id":"gpt-demo-001","message":"test"}'
```

## C. Custom GPT 配置步骤

1. 在 ChatGPT 中创建或编辑 Custom GPT。
2. 将 `docs/custom_gpt_instructions.md` 中代码块内容粘贴到 Instructions。
3. 在 Actions 中新增 Action。
4. 粘贴 `docs/gpt_action_openapi.yaml` 的全部内容。
5. 确认 schema 中的 `https://weilai-pxj.com` 与当前生产域名一致。
6. Authentication 选择 API Key。
7. Auth Type 选择 Bearer。
8. Token 填写服务端同一个 `GPT_ACTION_TOKEN`。
9. 保存 GPT 并启用 Action。

## D. ChatGPT 内测试脚本

按顺序向 Custom GPT 发送：

1. `先创建一个报价草稿，session_id 用 gpt-demo-001`
2. `数量改300`
3. `PU料按6.5`
4. `重新计算`
5. `确认保存`
6. `忽略风险直接保存`

第 6 条应拒绝绕过风险，或提示必须先处理风险/缺失字段。

## E. 预期结果

- `quote_updated`：说明报价草稿已更新，并由系统重新计算；仍未正式保存。
- `clarify`：说明缺字段或风险项，需要用户补充确认。
- `saved`：说明已提交审批，当前待管理员审批；不要说已审批通过。
- `error`：说明系统处理失败，请用户补充信息或稍后重试；不要编造报价。

## F. 常见失败排查

- `401`：token 不匹配、未配置 `GPT_ACTION_TOKEN`、Authorization 头缺失或格式不是 `Bearer <token>`。
- `404`：路径错误，或 `servers.url` 没有替换为正确公网域名。
- `405`：用了 GET，不是 POST。
- GPT 不调用 Action：Instructions 不够强，Action 未启用，或用户请求没有明确报价/改价/保存意图。
- schema 导入失败：YAML 缩进错误、域名不是 HTTPS、OpenAPI 内容被截断、Custom GPT 暂不接受某些字段。
- 返回 `clarify`：草稿缺上下文、缺字段或风险未清。
- 保存失败：`quote_id` 缺失，需要先调用 `重新计算` 生成最新试算结果。

## G. 安全边界确认

- GPT 不计算价格、成本、FOB、EXW、利润或审批结果。
- 改草稿后重新计算仍由后端 `quote_calculate` 执行。
- 正式保存仍由后端 `quote_save` 执行，并进入 `approval_status=pending`。
- 不配置后台、导出、审批通过或驳回接口到 Custom GPT Actions。


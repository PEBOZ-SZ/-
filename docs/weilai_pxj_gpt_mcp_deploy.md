# weilai-pxj.com GPT Action and MCP deployment

This document deploys the current auto quote system as a public HTTPS service for GPT Actions and, optionally, a public MCP endpoint. It does not change quote formulas, `quote_calculate`, or the formal `quote_save` pending approval flow.

## 1. DNS records

Add these DNS records in the `weilai-pxj.com` DNS console:

| Type | Host | Value | Notes |
| --- | --- | --- | --- |
| A | `@` | `159.75.112.178` | Auto quote web app, GPT Action, and MCP path |
| CNAME | `www` | `weilai-pxj.com` | Optional browser convenience |

Wait for DNS to resolve before issuing HTTPS certificates.

## 2. Server environment

Create a production env file on the server, for example `/opt/autoquote/.env.prod`, and set:

```bash
QUOTE_SERVER_HOST=0.0.0.0
QUOTE_SERVER_PORT=8776

# Keep admin private unless there is a separate VPN/IP allowlist plan.
QUOTE_ADMIN_SERVER_HOST=127.0.0.1
QUOTE_ADMIN_HTTP_PORT=8080

# Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
GPT_ACTION_TOKEN=REPLACE_WITH_LONG_RANDOM_TOKEN

# Optional Kimi/Moonshot provider
LLM_PROVIDER=moonshot
KIMI_API_KEY=REPLACE_WITH_REAL_KIMI_KEY
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=kimi-k2.6

# Public MCP, only listened on localhost and exposed through HTTPS reverse proxy.
PUBLIC_MCP_HOST=127.0.0.1
PUBLIC_MCP_PORT=8788
PUBLIC_MCP_TRANSPORT=streamable-http
```

Do not commit the real token or real Kimi key.

## 3. Start the quote web service

From the project directory:

```bash
cd /opt/autoquote
set -a
. ./.env.prod
set +a
python server.py
```

The front service should listen on `0.0.0.0:8776`. The reverse proxy below exposes only HTTPS 443 to the internet.

Local checks on the server:

```bash
curl -i http://127.0.0.1:8776/api/llm/status
curl -i http://127.0.0.1:8776/gpt/quote-agent
```

`GET /gpt/quote-agent` should return 405 because the Action endpoint is POST-only; that is okay.

## 4. HTTPS reverse proxy

Use Nginx or Caddy. Example Nginx config for the single public domain:

```nginx
server {
    listen 80;
    server_name weilai-pxj.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name weilai-pxj.com;

    ssl_certificate /etc/letsencrypt/live/weilai-pxj.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/weilai-pxj.com/privkey.pem;

    client_max_body_size 30m;

    # Public MCP over the same domain, only if enabled.
    location /mcp {
        proxy_pass http://127.0.0.1:8788/mcp;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }

    # Optional SSE MCP transport.
    location /sse {
        proxy_pass http://127.0.0.1:8788/sse;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }

    location /messages/ {
        proxy_pass http://127.0.0.1:8788/messages/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600s;
    }

    # Auto quote web app and GPT Action gateway.
    location / {
        proxy_pass http://127.0.0.1:8776;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
    }
}
```

If public MCP is not enabled yet, remove the `/mcp`, `/sse`, and `/messages/` locations for now.

## 5. GPT Action configuration

Use `docs/gpt_action_openapi.yaml` in the GPT Action schema. The server URL is:

```text
https://weilai-pxj.com
```

The Action endpoint is:

```text
POST https://weilai-pxj.com/gpt/quote-agent
```

Authentication:

```text
Bearer token
```

Use the exact value of `GPT_ACTION_TOKEN` from the server environment.

The OpenAPI schema must keep:

- `/gpt/quote-agent`
- `operationId: quoteAgent`
- `bearerAuth`

The GPT Action is a safe draft gateway. It does not expose approval, rejection, admin export, deletion, price write, or raw database query endpoints.

## 6. Public MCP configuration

The safe public MCP entrypoint is:

```bash
python -m mcp_server.public_mcp
```

Default local binding:

```text
127.0.0.1:8788
```

Public Connector URL:

```text
https://weilai-pxj.com/mcp
```

If a client requires SSE instead of streamable HTTP, set:

```bash
PUBLIC_MCP_TRANSPORT=sse
```

Then use:

```text
https://weilai-pxj.com/sse
```

Only these public MCP tools are registered:

- `quote_agent`
- `quote_history`
- `quote_get_detail`
- `quote_sheet_preview`
- `quote_approval_status`

Do not expose:

- `approve`
- `reject`
- `quote_admin`
- `delete`
- `price_admin_write`
- raw database query

## 7. Curl verification

Generate a token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Missing authorization must return `401`:

```bash
curl -i -X POST https://weilai-pxj.com/gpt/quote-agent \
  -H "Content-Type: application/json" \
  -d '{"session_id":"deploy-check","message":"数量改300"}'
```

Wrong token must return `401`:

```bash
curl -i -X POST https://weilai-pxj.com/gpt/quote-agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer wrong-token" \
  -d '{"session_id":"deploy-check","message":"数量改300"}'
```

Correct token should return a normal JSON shape with `quote_updated`, `clarify`, `saved`, or `error`:

```bash
curl -i -X POST https://weilai-pxj.com/gpt/quote-agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GPT_ACTION_TOKEN" \
  -d '{
    "session_id": "deploy-check",
    "message": "数量改300",
    "payload": {
      "product_name": "部署检查包",
      "quantities": [500],
      "items": [
        {"name": "PU料", "usage": 0.5, "unit_price": 6, "included_in_quote": true}
      ]
    }
  }'
```

MCP local health depends on the MCP client protocol. For a simple reachability check after starting `python -m mcp_server.public_mcp`:

```bash
curl -i https://weilai-pxj.com/mcp
```

The HTTP status may be protocol-specific, but it must reach the MCP server rather than DNS/TLS/proxy failure.

## 8. Safety guarantees

- Pricing is still produced by `quote_calculate`.
- The GPT Action and `quote_agent` MCP tool only pass user intent and structured context to the existing backend agent.
- Formal save still goes through `quote_save`.
- Saved quotes enter `approval_status=pending`; GPT does not approve or reject quotes.
- Admin approval/rejection endpoints are not included in the GPT Action schema or public MCP entrypoint.

## 9. Common failures

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `weilai-pxj.com` does not resolve | DNS record missing or not propagated | Add root A record to `159.75.112.178` and wait |
| Browser shows HTTPS/certificate error | Certificate not issued for the domain | Reissue Let's Encrypt cert for `weilai-pxj.com` |
| GPT Action gets 401 | Missing/wrong bearer token | Copy exact `GPT_ACTION_TOKEN` into GPT Action auth |
| GPT Action times out | Reverse proxy timeout too short or backend not running | Increase proxy timeouts and check `python server.py` |
| Upload fails for large sheets | Proxy body size too small | Set `client_max_body_size 30m` or larger |
| MCP connector cannot connect | MCP server not running or wrong transport path | Start `python -m mcp_server.public_mcp` and use `/mcp` for streamable HTTP |
| Admin page is not public | Expected safe default | Use SSH tunnel/VPN or a separate protected admin proxy plan |


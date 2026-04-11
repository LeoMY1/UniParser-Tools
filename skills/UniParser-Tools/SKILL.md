# UniParser-Tools Skill

Quick start guide for using UniParser-Tools to parse documents and extract structured content.

## Quick Start

### 1. Initialize Client

```python
import os
from uniparser_tools.api.clients import UniParserClient

api_key = os.getenv('UNIPARSER_API_KEY')
parser = UniParserClient(
    host="https://uniparser.dp.tech/",
    api_key=api_key
)
```

### 2. Parse a PDF File

```python
from uniparser_tools.common.constant import ParseMode, ParseModeTextual

result = parser.trigger_file(
    file_path="./document.pdf",
    textual=ParseModeTextual.DigitalExported,
    table=ParseMode.OCRFast,
    equation=ParseMode.OCRFast,
    figure=ParseMode.DumpBase64,
)

if result["status"] == "success":
    token = result["token"]
```

### 3. Get Results

```python
from uniparser_tools.common.constant import FormatFlag

# Option A: Get formatted content (Markdown/HTML/LaTeX)
result = parser.get_formatted(
    token,
    content=True,
    textual=FormatFlag.Markdown,
    table=FormatFlag.Markdown,
    equation=FormatFlag.Latex,
)
print(result["content"])

# Option B: Get structured data for programmatic access
from uniparser_tools.utils.convert import dict2obj

result = parser.get_result(token, pages_tree=True)
pages_tree = dict2obj(result["pages_tree"])

for page in pages_tree:
    for item in page:
        print(f"{item.type}: {item.format_as(FormatFlag.Markdown)}")
```

### 4. Async Callbacks (Webhooks)

For long-running tasks, use async mode with callbacks to avoid polling:

```python
result = parser.trigger_file(
    file_path="./document.pdf",
    sync=False,  # Required for async mode
    callback_url="https://your-server.com/api/callback",
    callback_secret="your-shared-secret",
    textual=ParseModeTextual.DigitalExported,
)

if result["status"] == "success":
    token = result["token"]
    print(f"Task submitted. Will callback when done. Token: {token}")
```

The service will POST to `callback_url` when parsing completes. The payload includes:
- `token`: The task token
- `status`: "success" or "error"
- `content`: The parsing result (same as `get_result()` output)
- `checksum`: HMAC-SHA256 signature for verification

See [Common Patterns](./patterns.md#pattern-3-async-processing-with-callback) for signature verification code.

## Common Patterns

| Pattern | Description | Reference |
|---------|-------------|-----------|
| Simple PDF to Markdown | Extract full text as Markdown | [Patterns](./patterns.md#pattern-1-simple-pdf-to-markdown) |
| Extract Figures | Get figures with captions | [Patterns](./patterns.md#pattern-2-extract-figures-with-captions) |
| Async Callback | Background processing with webhook | [Patterns](./patterns.md#pattern-3-async-processing-with-callback) |
| Mixed Formats | Different output formats per element | [Patterns](./patterns.md#pattern-4-mixed-format-output) |
| Parse Image | Parse image/snippet files | [Patterns](./patterns.md#pattern-5-parse-image-snippet) |
| Parse URL | Parse PDF from URL | [Patterns](./patterns.md#pattern-6-parse-pdf-from-url) |

## Callback Quick Reference

**Submit async task:**
```python
parser.trigger_file(file_path, sync=False, callback_url="...", callback_secret="...")
```

**Callback receives POST with:**
```json
{"token": "...", "status": "success", "content": {...}, "checksum": "..."}
```

**Verify signature:**
```python
import hmac, hashlib, json
expected = hmac.new(secret.encode(), json.dumps(content).encode(), hashlib.sha256).hexdigest()
hmac.compare_digest(received, expected)
```

For full callback implementation, see [patterns.md#pattern-3](./patterns.md#pattern-3-async-processing-with-callback).

## MCP Server

UniParser ships an MCP server (`mcp_server/`) that exposes the HTTP API as MCP tools over **stdio** (default), SSE, or Streamable HTTP.

### Tools

| Tool | Description |
|------|-------------|
| `uniparser_health` | `GET /health` — returns service health string |
| `uniparser_version` | `GET /version` — returns version info |
| `uniparser_parse_file` | Takes an absolute local PDF path, calls `trigger-file-async` → `get-formatted`, returns `content` text |
| `uniparser_parse_url` | Takes a public PDF URL, calls `trigger-url-async` → `get-formatted`, returns `content` text |

### Setup

```bash
cd mcp_server
uv sync          # install dependencies in isolation
uv run python -m uniparser_mcp  # start server
```

Two environment variables are **required** at runtime:

| Variable | Description |
|----------|-------------|
| `UNIPARSER_BASE_URL` | Base URL of the UniParser user service (e.g. `http://127.0.0.1:40001`) |
| `UNIPARSER_API_KEY` | API key passed as `X-API-Key` header |

Default parse parameters and output formats are controlled by `mcp_server/config.yaml`.

### MCP Client Integration (Cursor / Claude Code)

```json
{
  "mcpServers": {
    "uniparser": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/UniParser-Tools/mcp_server",
        "python",
        "-m",
        "uniparser_mcp"
      ],
      "env": {
        "UNIPARSER_BASE_URL": "http://127.0.0.1:40001",
        "UNIPARSER_API_KEY": "your-api-key"
      }
    }
  }
}
```

Replace `/path/to/UniParser-Tools/mcp_server` with the actual path on your machine.

### Transport Modes

Set `UNIPARSER_MCP_TRANSPORT` to override the default:

| Value | Description |
|-------|-------------|
| `stdio` (default) | Local subprocess — use for Cursor / Claude Code |
| `sse` | SSE transport |
| `streamable-http` (or `http`) | HTTP transport; configure host/port via `FASTMCP_HOST` / `FASTMCP_PORT` |

## Reference Documents

| Topic | File |
|-------|------|
| API Reference | [api-reference.md](./api-reference.md) |
| Common Patterns | [patterns.md](./patterns.md) |
| Data Classes | [data-classes.md](./data-classes.md) |
| Layout Types | [layout-types.md](./layout-types.md) |
| Utility Functions | [utilities.md](./utilities.md) |
| Important Notes | [notes.md](./notes.md) |

## Error Handling

```python
result = parser.trigger_file(file_path="./document.pdf")
if result["status"] != "success":
    print(f"Failed: {result.get('message')}")
    print(f"Details: {result.get('description')}")
```

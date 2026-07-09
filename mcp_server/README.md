# UniParser MCP Server

基于 [Model Context Protocol](https://modelcontextprotocol.io/) 的 MCP 服务，通过单一工具 `uniparser_parse` 调用 [UniParser](https://uniparser.dp.tech/) API（经 `uniparser-tools` 的 `UniParserClient`）。

## Tool

| Tool | 说明 |
|------|------|
| `uniparser_parse` | 解析本地 PDF、本地图片或公网 PDF URL；落盘 Markdown + `pages_tree.json`；返回路径与 `content_preview` |

### `uniparser_parse` 参数

提供 **三选一** 输入：`file_path`、`image_path`、`pdf_url`。

| 参数 | 说明 |
|------|------|
| `output_dir` | 可选；默认 `~/Uni-Parser-Skill/<stem>/` |
| `overwrite` | 输出目录已存在时是否覆盖 |
| `async_mode` | `sync=false` 提交后轮询直至完成 |
| `textual` … `molecule` | 7 个语义字段，默认 scientific-paper preset |

成功返回 JSON（Pydantic）：`markdown_path`、`pages_tree_path`、`content_preview`（默认 2000 字）、`message` 等。

健康检查、版本查询、按 token 手动恢复请使用 CLI：`uniparser health`、`uniparser version`、`uniparser fetch`。

## 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `UNIPARSER_API_KEY` | 必填，`X-API-Key` | — |
| `UNIPARSER_BASE_URL` | API 根 URL | `https://uniparser.dp.tech` |
| `OUTPUT_DIR` | 输出根目录 | `~/Uni-Parser-Skill` |
| `UNIPARSER_PREVIEW_CHARS` | `content_preview` 长度 | `2000` |
| `UNIPARSER_MCP_TRANSPORT` | `stdio` / `sse` / `streamable-http` | `stdio` |

## 安装与运行

```bash
cd mcp_server
uv sync
uv run python -m uniparser_mcp
```

## 测试

```bash
cd mcp_server
uv sync --extra dev
uv run pytest tests/ -v
```

## Cursor 接入示例

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
        "UNIPARSER_API_KEY": "your-api-key"
      }
    }
  }
}
```

`UNIPARSER_BASE_URL` 可省略（默认云服务）；本地自托管时设置为 `http://127.0.0.1:40001` 等。

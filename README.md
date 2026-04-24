# UniParser-Tools

UniParser Tools 是一个强大的文档解析工具包，支持对 PDF 文件和图片进行智能解析，提取文本、表格、图片、公式、分子结构等多种语义元素。

本工具包提供了完整的 Python API，方便开发者快速集成文档解析能力到自己的项目中。

## 主要功能

### 核心解析能力

- **文本提取 textual**：支持数字导出和 OCR 快速识别
- **表格识别 table**：自动识别表格结构并提取内容
- **公式识别 equation**：识别数学公式和化学表达式
- **分子识别 molecule**：提取化学分子式及其索引
- **反应式识别 expression**：提取化学反应式
- **图表识别 chart**：识别简单图表元素
- **图片识别 figure**：提取图片

### 输出格式

支持多种输出格式，满足不同场景需求：

- **Content (End2End)**：全文文本内容，适用于 LLM 等场景
- **Objects**：JSON 格式的语义块，适用于语义分析
- **Pages dict**：原始解析格式，按页面组织的详细语义块
- **Pages tree**：带嵌套关系的树结构，支持复杂语义分析

### 格式化输出

支持多种格式化输出方式：

- **Markdown**：Markdown 格式输出 ⭐️
- **HTML**：HTML 格式输出 ⭐️
- **LaTeX**：LaTeX 格式输出
- **Plain**：纯文本格式输出
- **Markup**：标记文本格式输出

### 高级功能

- **图文对提取**：自动提取图片及其对应的标题、图注
- **表格结构化提取**：提取表格及其表题、表注
- **分子索引关联**：提取分子结构及其索引信息
- **公式索引关联**：提取公式及其编号信息

## 安装

```bash
pip install -r requirements.txt
```

或者安装为可编辑包：

```bash
pip install -e .
```

## API-Key 配置

所有请求都通过 `X-API-Key` 请求头认证，`UniParserClient` 会自动注入。

- **获取方式**：在 UniParser 服务首页（如 `https://uniparser.dp.tech/`）注册访客账号，或向运维/业务方申请长期 API-Key。
- **推荐存储**：使用环境变量 `UNIPARSER_API_KEY`，避免在代码中硬编码。
- **常见错误**：`401` 表示缺失/过期；`429` 表示触发并发上限（公开服务最大 5 并发）。

```python
import os
parser = UniParserClient(
    host="https://uniparser.dp.tech/",
    api_key=os.getenv("UNIPARSER_API_KEY"),
)
```

## 解析配置：7 个语义类 + 2 个枚举

提交解析任务时（`trigger_file` / `trigger_snip` / `trigger_url`），可分别设置 7 类语义元素的处理模式：

| 字段 | 含义 | 枚举类型 |
|------|------|---------|
| `textual` | 普通文本（段落、标题等） | `ParseModeTextual` |
| `equation` | 数学公式 | `ParseMode` |
| `table` | 表格 | `ParseMode` |
| `chart` | 图表 | `ParseMode` |
| `figure` | 图片 / 插图 | `ParseMode` |
| `expression` | 化学反应式 | `ParseMode` |
| `molecule` | 化学分子结构 | `ParseMode` |

### `ParseMode`（除 textual 外都用这个）

| 取值 | 名称 | 含义 |
|------|------|------|
| `-3` / `-2` | `DumpHosting` / `DumpLocal` | 保留接口，默认关闭 |
| `-1` | `DumpBase64` | 禁用解析，输出原始图像 Base64 |
| `0`  | `Disable`   | 禁用解析，不输出 |
| `1`  | `OCRFast`   | 快速 OCR（默认） |
| `2`  | `OCRHighQuality` | 高质 OCR |

### `ParseModeTextual`（仅用于 `textual`）

| 取值 | 名称 | 含义 |
|------|------|------|
| `-1` | `DumpBase64` | 输出原始图像 Base64 |
| `0`  | `Disable`   | 不解析、不输出 |
| `1`  | `OCRFast`   | 快速 OCR |
| `2`  | `OCRHighQuality` | 高质 OCR，支持行内公式 |
| `3`  | `DigitalExported` | 从数字原生 PDF 直接抽取文字 |

## 快速开始

> ‼️‼️‼️ 以下仅为代码功能示例，具体运行代码请参考 `playground/*.ipynb` ‼️‼️‼️

### 1. 初始化客户端

```python
import os
from uniparser_tools.api.clients import UniParserClient

# 设置 API 密钥
api_key = os.getenv('UNIPARSER_API_KEY')

# 初始化客户端
parser = UniParserClient(
    host="https://uniparser.dp.tech/",
    api_key=api_key
)
```

### 2. 解析 PDF 文件（科学文献推荐默认）

```python
from uniparser_tools.common.constant import ParseMode, ParseModeTextual

# 科学文献解析模式（推荐默认值）
result = parser.trigger_file(
    pdf_path="./example.pdf",
    textual=ParseModeTextual.OCRHighQuality,  # high quality
    equation=ParseMode.OCRHighQuality,        # high quality
    table=ParseMode.OCRHighQuality,           # high quality
    chart=ParseMode.DumpBase64,               # original image base64
    figure=ParseMode.DumpBase64,              # original image base64
    expression=ParseMode.DumpBase64,          # original image base64
    molecule=ParseMode.OCRFast,               # fast
)

if result["status"] == "success":
    token = result["token"]
    print(f"解析成功，token: {token}")
```

### 3. 获取解析结果

#### 输出配置（`get_result` / `get_formatted` 通用开关）

| 开关 | 默认 | 说明 |
|------|------|------|
| `content` | `True` | 返回全文纯/富文本，适合 LLM |
| `objects` | `False` | JSON 语义块列表，适合语义分析 |
| `pages_dict` | `False` | 按页组织的原始解析布局 |
| `pages_tree` | `False` | 带父子关系的嵌套树，适合复杂分析 |
| `return_half` | `False` | 解析进行中即取已完成部分 |
| `molecule_source` | `False` | 返回分子原始源（SMILES/mol 等） |

同一 token 可复用，多次获取不同组合不会重复计费。

#### 输出格式（`FormatFlag`，仅作用于 `content` / `objects` 中的文本字段）

| 取值 | 适用场景 |
|------|----------|
| `FormatFlag.Plain` | 纯文本，适合检索 |
| `FormatFlag.Markup` | 默认标记文本 |
| `FormatFlag.Markdown` | ⭐ 推荐给 LLM |
| `FormatFlag.Latex` | LaTeX，适合公式 |
| `FormatFlag.Html` | HTML，适合表格 |

```python
from uniparser_tools.common.constant import FormatFlag

# 获取 Markdown 格式的全文内容
result = parser.get_formatted(
    token,
    content=True,
    textual=FormatFlag.Markdown,
    table=FormatFlag.Markdown,
    equation=FormatFlag.Markdown,
)

if result["status"] == "success":
    print(result["content"])
```

### 4. 使用异步回调 (Callbacks)

UniParser 支持在异步任务完成后通过 HTTP POST 回调结果到指定地址。这对于长耗时任务非常有用，无需轮询结果。

```python
# 提交带回调地址的异步解析任务
result = parser.trigger_file(
    pdf_path="./example.pdf",
    sync=False,  # 必须为 False 才能触发异步回调
    callback_url="https://your-server.com/api/callback",
    callback_secret="your-shared-secret",  # 用于校验回调内容的签名
    textual=ParseModeTextual.OCRHighQuality,
    equation=ParseMode.OCRHighQuality,
    table=ParseMode.OCRHighQuality,
    chart=ParseMode.DumpBase64,
    figure=ParseMode.DumpBase64,
    expression=ParseMode.DumpBase64,
    molecule=ParseMode.OCRFast,
)

if result["status"] == "success":
    token = result["token"]
    print(f"异步任务已提交，完成后将回调到指定地址。Token: {token}")
```

回调请求的 Payload 将包含 `checksum` 和 `content`。你可以使用 `callback_secret` 对 `content` 进行 HMAC-SHA256 签名校验，以确保内容未被篡改。

### 5. 解析图片文件

```python
from uniparser_tools.common.constant import ParseMode, ParseModeTextual

# 提交图片解析任务
result = parser.trigger_snip(
    snip_path="./example.png",
    textual=ParseModeTextual.OCRFast,
    table=ParseMode.OCRFast,
    molecule=ParseMode.OCRFast,
)

if result["status"] == "success":
    token = result["token"]
    # 使用 token 获取解析结果
```

## 使用示例

### 图文对提取

详细示例请参考 `playground/app.caption_extraction.ipynb`：

```python
import json
import os
from uniparser_tools.tools.caption_extraction.main import main

# 设置文件路径和保存目录
pdf_path = "./example.pdf"
save_dir = "./outputs/caption_extraction"
os.makedirs(save_dir, exist_ok=True)

# 首先需要提交解析任务并获取 token（参考前面的步骤）
# result = parser.trigger_file(pdf_path, ...)
# token = result["token"]

# 获取解析结果
result = parser.get_result(token, pages_dict=True)
json_path = f"{save_dir}/{token}.json"
json.dump(result["pages_dict"], open(json_path, "w"), indent=4)

# 提取图文对
results = main(
    token=token,
    pdf_path=pdf_path,
    json_path=json_path,
    save_dir=save_dir,
    dpi=300,
    log_level="INFO",
)

# 处理提取结果
if results:
    extracted = results["extracted"]
    for k, item in extracted.items():
        # item.main_image: 主图片
        # item.caption_image: 图题图片
        # item.group_image: 组合图片
        # item.captions: 图题文本列表
        # item.keywords: 关键词列表
        pass
```

### 多种格式输出

可以在同一次格式化输出中设置不同语义元素的输出模式：

```python
from uniparser_tools.common.constant import FormatFlag

# token 和 parser 需要从前面的步骤获取
result = parser.get_formatted(
    token,
    content=True,
    textual=FormatFlag.Markdown,    # 文本使用 Markdown
    table=FormatFlag.Html,          # 表格使用 HTML
    equation=FormatFlag.Latex,       # 公式使用 LaTeX
)

if result["status"] == "success":
    print(result["content"])
```

## 面向 AI Agent

本仓库内置了 Cursor / Claude Code 兼容的 Skill 文件：

```
skills/UniParser-Tools/SKILL.md
```

当你的 AI 编程助手（Cursor、Claude Code、Codex、Gemini Code 等）需要调用 UniParser-Tools 时，建议先读取该 `SKILL.md`，其中包含快速开始、常见模式、MCP 集成、数据类与 API 参考。配套的进一步文档位于同目录下：

- `skills/UniParser-Tools/api-reference.md`
- `skills/UniParser-Tools/patterns.md`
- `skills/UniParser-Tools/data-classes.md`
- `skills/UniParser-Tools/layout-types.md`
- `skills/UniParser-Tools/utilities.md`
- `skills/UniParser-Tools/notes.md`

## MCP Server

UniParser 提供了基于 [Model Context Protocol](https://modelcontextprotocol.io/) 的 MCP 服务，位于 `mcp_server/` 目录，支持通过 MCP 工具调用 UniParser HTTP API。

### 可用工具

| 工具 | 说明 |
|------|------|
| `uniparser_health` | 检查服务健康状态 |
| `uniparser_version` | 获取服务版本信息 |
| `uniparser_parse_file` | 解析本机 PDF（传入绝对路径），返回 `content` 文本 |
| `uniparser_parse_url` | 解析公网 PDF URL，返回 `content` 文本 |

### 快速启动

```bash
cd mcp_server
uv sync                          # 安装依赖（与主项目隔离）
uv run python -m uniparser_mcp   # 启动 MCP 服务（stdio 模式）
```

运行时必须设置以下环境变量：

| 变量 | 说明 |
|------|------|
| `UNIPARSER_BASE_URL` | UniParser 用户服务根 URL，例如 `http://127.0.0.1:40001` |
| `UNIPARSER_API_KEY` | API 密钥，对应请求头 `X-API-Key` |

默认解析参数和输出格式见 `mcp_server/config.yaml`。

### 接入 Cursor / Claude Code

在 MCP 配置文件中添加（将路径替换为本机实际路径）：

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

传输模式默认为 `stdio`，可通过 `UNIPARSER_MCP_TRANSPORT` 环境变量切换为 `sse` 或 `streamable-http`。

详细文档见 [`mcp_server/README.md`](./mcp_server/README.md)。

## 项目结构

```
uniparser_tools/
├── api/              # API 客户端
├── common/           # 通用常量和数据类
├── tools/            # 工具模块
│   └── caption_extraction/  # 图文对提取工具
├── utils/            # 工具函数
└── order/            # 排序算法

mcp_server/           # MCP 服务（独立子项目）
├── uniparser_mcp/    # MCP server 实现
├── config.yaml       # 默认解析参数配置
└── pyproject.toml    # 独立依赖管理

playground/
├── 01.quick_start.ipynb          # 快速开始教程
├── 02.advance.ipynb              # 高级用法教程
├── 04.use_callbacks.py           # 异步回调功能演示
├── app.caption_extraction.ipynb  # 图文对提取示例
└── app.molecule_extracrtion.ipynb # 分子提取示例
```

## 详细文档

项目提供了丰富的示例和教程，位于 `playground/` 目录下：

- **快速开始**：`playground/01.quick_start.ipynb` - 基础用法教程，包括 PDF 和图片解析、多种格式输出
- **高级用法**：`playground/02.advance.ipynb` - 高级功能教程，包括图片+图题+图注、表格+表题+表注、分子+分子索引、公式+公式索引的提取
- **异步回调**：`playground/04.use_callbacks.py` - 异步回调演示，用于在异步解析任务完成后自动接收通知和结果
- **图文对提取**：`playground/app.caption_extraction.ipynb` - 图文对提取完整示例
- **分子提取**：`playground/app.molecule_extracrtion.ipynb` - 分子结构提取示例

## 注意事项

1. **并发限制**：公开 UniParser 服务最高仅允许 5 并发，使用时请注意控制并发数量
2. **API 密钥**：需要配置有效的 API 密钥才能使用服务，可通过环境变量 `UNIPARSER_API_KEY` 设置
3. **服务端点**：不同 host 对应功能不完全相同，解析质量也不一样，具体请在售后群中咨询
4. **图文对提取**：必须使用特定端口（30001）进行解析，其他接口不支持提取图文对
5. **Token 复用**：解析任务提交后会返回一个 token，可以持有该 token 多次获取不同格式的结果

## 依赖要求

主要依赖包请参考 `requirements.txt`，包括：

- PyMuPDF
- pandas
- pillow
- opencv-python
- numpy
- scipy
- lxml
- 等

## 许可证

[待补充]

## 联系方式

如有问题，请在售后群中咨询。

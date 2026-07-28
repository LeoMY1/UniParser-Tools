# PDF 原位翻译（`uniparser-agent translate`）

将本地 PDF 翻译为简体中文，并生成一份尽量保留原页面结构、图片和版式的译文 PDF。

适合需要快速阅读外文论文、技术报告和普通文档，同时希望译文仍能对应原文页面位置的场景。

> 当前仅支持翻译为简体中文（`zh-CN`），输入必须是本地 PDF。

## 能做什么

- 将 PDF 中的标题、摘要、正文、参考文献和图片说明翻译为中文
- 在原文位置显示译文，保留原 PDF 的页面、图片和整体布局
- 自动统一文档中的专业术语，也支持用户提供指定译法
- 保留正文中的行内公式，避免翻译时破坏公式内容
- 支持复用已有 `pages_tree.json`，方便重新翻译而不重复解析
- 翻译失败的内容保留原文，避免输出空白区域
- 输出译文 PDF、逐段翻译结果和运行摘要，便于阅读与检查

## 什么时候使用

推荐用于：

- 将英文论文或技术报告快速翻译为中文
- 希望译文与原文页面位置基本对应，方便对照阅读
- 文档中有较多专业术语，需要统一译法
- 已有 UniParser 解析结果，希望更换模型或术语表重新翻译
- 需要保留翻译记录，检查哪些内容成功、失败或可能溢出

不建议用于：

- 只需要提取纯文本或 Markdown：使用 `uniparser-agent parse`
- 需要从试卷中提取题目、答案和解析：使用 `uniparser-agent vqa`
- 需要翻译图片中的嵌字、表格正文或独立公式
- 对出版级排版、字符级样式和原字体完全一致有严格要求

## 环境要求

- Python 3.11+
- 已安装 `uniparser-agent`
- 本地 PDF 文件
- 未使用 `--pages-tree` 时，需要 UniParser API Key
- OpenAI 兼容的 LLM 服务

## 安装

```bash
cd uniparser_agent
uv sync
```

或在已有虚拟环境中安装：

```bash
cd uniparser_agent
uv pip install -e ".[dev]"
```

## 配置

设置 UniParser 和 LLM 环境变量：

```bash
export UNIPARSER_API_KEY="your-uniparser-key"
export OPENAI_API_KEY="your-llm-key"
export OPENAI_BASE_URL="https://example.com/v1"
export OPENAI_MODEL="your-model"
```

| 变量 | 是否必填 | 用途 |
|------|----------|------|
| `UNIPARSER_API_KEY` | 未使用 `--pages-tree` 时必填 | 解析原始 PDF |
| `OPENAI_API_KEY` | 必填 | 调用翻译模型 |
| `OPENAI_BASE_URL` | 必填 | OpenAI 兼容服务地址 |
| `OPENAI_MODEL` | 必填 | 翻译模型名称 |
| `UNIPARSER_BASE_URL` | 可选 | 自定义 UniParser 服务地址 |

也可以在命令行中使用 `--api-key`、`--base-url` 和 `--model` 覆盖 LLM 配置。

不要把真实 API Key 写入源码或提交到仓库。

## 快速开始

### 翻译一个 PDF

```bash
uv run uniparser-agent translate /path/to/paper.pdf \
  -o ./translate_out \
  --overwrite
```

翻译完成后，主结果为：

```text
translate_out/translated.pdf
```

### 使用已有解析结果

如果 PDF 已经通过 UniParser 解析，可以复用 `pages_tree.json`：

```bash
uv run uniparser-agent translate /path/to/paper.pdf \
  --pages-tree /path/to/pages_tree.json \
  -o ./translate_out \
  --overwrite
```

使用该方式时不需要 `UNIPARSER_API_KEY`，但仍必须提供与 `pages_tree.json` 对应的原始 PDF，用于生成最终译文。

### 指定源语言

默认自动判断源语言；也可以提供提示：

```bash
uv run uniparser-agent translate ./paper.pdf \
  --source-lang en \
  -o ./translate_out \
  --overwrite
```

### 使用自定义术语表

术语表使用 CSV 格式，至少包含 `source` 和 `target`：

```csv
source,target
large language model,大语言模型
retrieval-augmented generation,检索增强生成
```

运行：

```bash
uv run uniparser-agent translate ./paper.pdf \
  --glossary ./terms.csv \
  -o ./translate_out \
  --overwrite
```

自动术语表默认开启；手动术语表中的译法优先。

如果不需要自动抽取术语：

```bash
uv run uniparser-agent translate ./paper.pdf \
  --no-auto-glossary \
  -o ./translate_out \
  --overwrite
```

### 使用自定义中文字体

```bash
uv run uniparser-agent translate ./paper.pdf \
  --font /path/to/NotoSansCJK-Regular.ttc \
  -o ./translate_out \
  --overwrite
```

未指定字体时，程序会自动选择系统中可用的中文字体。

## 常用参数

```text
uniparser-agent translate [OPTIONS] PDF_PATH
```

| 参数 | 用途 |
|------|------|
| `PDF_PATH` | 必填，本地 PDF 路径 |
| `-o` / `--output-dir` | 指定输出目录；默认 `./translate_out` |
| `--source-lang` | 提供源语言提示；默认自动判断 |
| `--pages-tree` | 复用已有 `pages_tree.json` |
| `--glossary` | 使用手动术语表 CSV |
| `--no-auto-glossary` | 关闭自动术语抽取 |
| `--font` | 指定中文字体文件 |
| `--overwrite` | 删除并重建已存在的输出目录 |
| `--debug-layout` | 额外生成布局检查 PDF |
| `--json` | 在终端输出机器可读的运行摘要 |

查看全部参数：

```bash
uv run uniparser-agent translate --help
```

## 会返回什么

默认输出目录结构如下：

```text
translate_out/
├── translated.pdf
├── translate_units.jsonl
├── run_meta.json
├── parse/
│   └── pages_tree.json
├── llm_raw/
├── glossary_auto.json
├── glossary_auto.csv
└── layout_debug.pdf
```

部分文件只在对应功能启用或有结果时生成。

### 主要结果

| 文件 | 用途 |
|------|------|
| `translated.pdf` | 最终中文译文 PDF，日常使用主要查看此文件 |
| `translate_units.jsonl` | 每段原文、译文和处理状态，可用于检查漏译或失败内容 |
| `run_meta.json` | 本次运行的语言、模型、数量、耗时和输出路径摘要 |

### 辅助结果

| 文件或目录 | 用途 |
|------------|------|
| `parse/pages_tree.json` | UniParser 解析结果，可用于后续重新翻译 |
| `glossary_auto.json` / `.csv` | 自动提取的术语及中文译法 |
| `llm_raw/` | 翻译模型的原始返回结果，主要用于问题排查 |
| `layout_debug.pdf` | 标记翻译区域的调试 PDF，仅使用 `--debug-layout` 时生成 |

### 译文 PDF 中的内容

默认会翻译：

- 文档标题和章节标题
- 摘要和正文段落
- 参考文献文本
- 表格标题、图片标题和说明文字

默认保持原样：

- 表格正文
- 独立公式
- 图片、图表和分子结构
- 页眉、页脚、页码和目录

如果某段翻译失败，该区域会保留原文，不会被替换为空白内容。

## 如何检查结果

1. 首先打开 `translated.pdf`，检查整体译文和页面布局。
2. 如果发现漏译，查看 `translate_units.jsonl` 中对应内容的状态。
3. 如果译文超出原区域，可使用 `--debug-layout` 重新运行并查看 `layout_debug.pdf`。
4. 如果术语不一致，提供手动术语表后重新翻译。
5. 如果只想更换模型或术语表，复用 `--pages-tree` 可以避免再次解析 PDF。

常见状态：

| 状态 | 含义 |
|------|------|
| `translated` | 已成功翻译并写入 PDF |
| `skipped` | 该内容不在默认翻译范围内 |
| `failed` | 翻译失败，最终 PDF 保留原文 |
| `overflow` | 已绘制译文，但内容可能超出可用区域，需要人工检查 |

## 常见问题

### 为什么使用 `--pages-tree` 还需要原 PDF？

`pages_tree.json` 提供文字和位置信息，原 PDF 用于保留页面、图片和版式，并生成最终的 `translated.pdf`。

### 为什么部分文字没有翻译？

表格正文、独立公式、图片文字、页眉页脚等默认不翻译。模型调用失败的内容也会保留原文，可通过 `translate_units.jsonl` 查看状态。

### 为什么输出目录已存在时报错？

程序默认避免覆盖已有结果。确认可以删除旧目录后，添加 `--overwrite`。

### 如何改善专业术语翻译？

使用 `--glossary` 提供手动术语表。手动译法会优先于自动术语结果。

### 如何减少重复解析？

首次运行后保留 `parse/pages_tree.json`，后续使用 `--pages-tree` 重新翻译。

### `overflow` 是否表示翻译失败？

不是。它表示译文已经绘制，但可能没有完整容纳在可用区域内，应人工检查对应页面。

## 当前限制

- 仅支持本地 PDF，不能直接输入图片或 PDF URL
- 目标语言固定为简体中文
- 表格正文、独立公式和图片中的文字默认不翻译
- 采用段落级原位替换，不能保证达到出版级排版效果
- 过长译文可能与下方内容重叠或出现 `overflow`
- 复杂多栏、旋转文字、扫描件或异常版面可能需要人工检查

## 相关命令

| 需求 | 推荐命令 |
|------|----------|
| 只解析 PDF，获取结构化结果 | `uniparser-agent parse` |
| 将 PDF 翻译为中文并保留原页面 | `uniparser-agent translate` |
| 从习题或试卷中提取 VQA 数据 | `uniparser-agent vqa` |
| 构建化学专利分子库 | `uniparser-agent run` / `ingest` |

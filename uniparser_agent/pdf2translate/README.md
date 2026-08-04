# PDF 原位翻译（`uniparser-agent translate`）

将本地 PDF 翻译为简体中文，并生成一份尽量保留原页面、图片和版式的译文 PDF。

适合阅读外文论文、技术报告和普通文档。译文会写回原文所在区域，方便按页对照；同时保留逐段翻译记录，便于检查漏译、失败和排版溢出。

> 当前仅支持本地 PDF，目标语言固定为简体中文（`zh-CN`）。

## 核心能力

- 翻译文档标题、章节标题、摘要、正文、参考文献和图表说明
- 在原文位置绘制中文译文，保留原 PDF 的页面、图片和整体布局
- 自动提取专业术语并统一译法，也支持用户提供指定术语表
- 保留正文中的行内公式，避免翻译过程破坏公式内容
- 支持复用已有 `pages_tree.json`，更换模型或术语表时无需重复解析
- 翻译失败时保留原文，避免最终 PDF 出现空白区域
- 输出译文 PDF、逐段翻译结果和运行摘要，方便阅读与检查

## 安装

运行要求：

- Python 3.11+
- 本地 PDF 文件
- OpenAI 兼容的 LLM 服务
- 输入原始 PDF 时，需要 UniParser API Key

在 `uniparser_agent` 目录安装依赖：

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
| `PDF_TRANSLATE_BATCH_SIZE` | 可选 | 每批翻译单元数，默认 `12` |
| `PDF_TRANSLATE_MAX_WORKERS` | 可选 | 并行翻译批次数，默认 `4` |

也可以通过 `--api-key`、`--base-url` 和 `--model` 在命令行中覆盖 LLM 配置。

使用已有 `pages_tree.json` 时不需要 `UNIPARSER_API_KEY`，但仍需配置 LLM 服务。

不要把真实 API Key 写入源码或提交到仓库。

## 快速开始

### 翻译一个 PDF

```bash
uv run uniparser-agent translate /path/to/paper.pdf \
  -o ./translate_out
```

完成后主要查看：

```text
translate_out/translated.pdf
```

该文件是保留原页面和图片的中文译文 PDF。

## 使用指南

### 使用已有解析结果

如果 PDF 已经通过 UniParser 解析，可以复用对应的 `pages_tree.json`：

```bash
uv run uniparser-agent translate /path/to/paper.pdf \
  --pages-tree /path/to/pages_tree.json \
  -o ./translate_out
```

该方式不会再次消耗 UniParser 解析额度。原 PDF 仍然必填，用于保留页面、图片和版式，并生成最终译文。

### 指定源语言

默认由翻译模型判断源语言。也可以提供语言提示：

```bash
uv run uniparser-agent translate ./paper.pdf \
  --source-lang en \
  -o ./translate_out
```

`--source-lang` 只提供源语言提示，不会改变简体中文目标语言。

### 使用自定义术语表

术语表使用 CSV 格式，必须包含 `source` 和 `target` 两列：

```csv
source,target
large language model,大语言模型
retrieval-augmented generation,检索增强生成
```

也可以增加可选的 `tgt_lng` 列；与当前目标语言不匹配的行会被忽略。

```bash
uv run uniparser-agent translate ./paper.pdf \
  --glossary ./terms.csv \
  -o ./translate_out
```

自动术语提取默认开启。手动术语表与自动术语重复时，手动译法优先。

如不需要自动提取术语：

```bash
uv run uniparser-agent translate ./paper.pdf \
  --no-auto-glossary \
  -o ./translate_out
```

### 使用自定义中文字体

```bash
uv run uniparser-agent translate ./paper.pdf \
  --font /path/to/NotoSansCJK-Regular.ttc \
  -o ./translate_out
```

支持 TTF、OTF 等字体文件。未指定时，程序会尝试使用系统中可用的中文字体。

### 检查翻译区域

```bash
uv run uniparser-agent translate ./paper.pdf \
  --debug-layout \
  -o ./translate_out
```

开启后会额外生成 `layout_debug.pdf`，用于检查翻译区域与原文位置是否匹配。

## 常用参数

```text
uniparser-agent translate [OPTIONS] PDF_PATH
```

| 参数 | 用途 |
|------|------|
| `PDF_PATH` | 必填，本地 PDF 路径 |
| `-o` / `--output-dir` | 首选输出目录，默认 `./translate_out` |
| `--source-lang` | 提供源语言提示，默认自动判断 |
| `--pages-tree` | 复用已有 `pages_tree.json` |
| `--glossary` | 使用手动术语表 CSV |
| `--no-auto-glossary` | 关闭自动术语提取 |
| `--font` | 指定译文使用的中文字体文件 |
| `--debug-layout` | 额外生成翻译区域检查 PDF |
| `--api-key` | 覆盖 `OPENAI_API_KEY` |
| `--base-url` | 覆盖 `OPENAI_BASE_URL` |
| `--model` | 覆盖 `OPENAI_MODEL` |
| `--enable-thinking` | 为兼容的 Qwen 服务开启思考模式 |
| `--json` | 在终端输出机器可读的运行摘要 |

查看全部参数：

```bash
uv run uniparser-agent translate --help
```

## 输出结果

默认输出目录如下：

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

部分文件只在对应功能启用或产生结果时生成。

### 主要结果

| 文件 | 用途 |
|------|------|
| `translated.pdf` | **最终中文译文 PDF**，日常使用主要查看此文件 |
| `translate_units.jsonl` | 逐段原文、译文、位置和处理状态，用于检查漏译或失败内容 |
| `run_meta.json` | 本次运行的语言、模型、数量、耗时和文件路径摘要 |

### 辅助结果

| 文件或目录 | 用途 |
|------------|------|
| `parse/pages_tree.json` | UniParser 解析结果，可用于后续重新翻译 |
| `glossary_auto.json` / `glossary_auto.csv` | 自动提取的术语及中文译法 |
| `llm_raw/` | 翻译模型的原始返回结果，主要用于问题排查 |
| `layout_debug.pdf` | 标记翻译区域的检查 PDF，仅使用 `--debug-layout` 时生成 |

输出目录已存在时，程序不会覆盖或删除旧结果，而是自动创建第一个可用的同级目录。例如 `translate_out` 已存在时使用 `translate_out_1`。请以命令最终返回的 `Output directory` 为准。

### 翻译单元状态

`translate_units.jsonl` 中每行对应一个文档内容块，常见状态如下：

| 状态 | 含义 |
|------|------|
| `translated` | 已成功翻译并写入 PDF |
| `skipped` | 该内容不在默认翻译范围内 |
| `failed` | 翻译或绘制失败；翻译失败时保留原文，绘制失败时需要检查对应区域 |
| `overflow` | 已绘制译文，但可能超出可用区域，需要人工检查 |

### 默认翻译范围

默认翻译：

- 文档标题和章节标题
- 摘要与正文段落
- 参考文献文本
- 表格标题、图片标题和说明文字

默认保持原样：

- 表格正文
- 独立公式
- 图片、图表和分子结构
- 图片中的嵌入文字
- 页眉、页脚、页码和目录

正文中的行内公式会尽量保留。渲染时会将部分 LaTeX 表达转换为适合阅读的文本形式。

## 结果检查

1. 打开 `translated.pdf`，检查译文内容和整体页面布局。
2. 如果发现漏译或原文未替换，查看 `translate_units.jsonl` 中对应内容的状态和错误信息。
3. 如果译文与其他内容重叠，使用 `--debug-layout` 重新运行并检查 `layout_debug.pdf`。
4. 如果专业术语不一致，提供手动术语表后重新翻译。
5. 只更换模型、字体或术语表时，使用 `--pages-tree` 复用首次解析结果。

## 常见问题

### 为什么使用 `--pages-tree` 还需要原 PDF？

`pages_tree.json` 只提供文本、类型和位置信息。原 PDF 用于保留页面、图片和原有版式，并生成最终的 `translated.pdf`。

### 为什么部分文字没有翻译？

表格正文、独立公式、图片文字、页眉页脚等内容默认不翻译。模型调用失败的内容会保留原文；其他失败情况可通过 `translate_units.jsonl` 查看具体状态。

### 为什么实际输出目录带有数字后缀？

程序不会覆盖已有结果。首选目录已存在时，会自动创建 `_1`、`_2` 等带数字后缀的同级目录。

### 如何改善专业术语翻译？

使用 `--glossary` 提供手动术语表。手动译法会优先于自动提取的术语结果。

### 如何更换模型后重新翻译？

保留首次运行生成的 `parse/pages_tree.json`，然后使用 `--pages-tree` 重新运行。可以通过环境变量或 `--model` 指定新的翻译模型。

### `overflow` 是否表示翻译失败？

不是。它表示译文已经绘制，但可能没有完整容纳在可用区域内，应对照原文人工检查对应页面。

## 当前限制

- 仅支持本地 PDF，不能直接输入图片或 PDF URL
- 目标语言固定为简体中文
- 表格正文、独立公式和图片中的文字默认不翻译
- 采用段落级原位替换，不能保证达到出版级排版效果
- 同类内容使用统一字号；过长译文可能与下方内容重叠或出现 `overflow`
- 复杂多栏、旋转文字、扫描件或异常版面可能需要人工检查
- 翻译质量依赖原始文档解析质量和所选 LLM，关键内容建议对照原文核验

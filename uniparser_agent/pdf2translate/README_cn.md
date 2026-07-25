# pdf2translate

基于 UniParser 的 PDF 原位视觉翻译（MVP）。

英文说明见 [README.md](README.md)。

## 功能流程

1. 用 UniParser 解析 PDF（或复用已有 `pages_tree.json`）
2. 按 bbox 选取文本块（`paragraph` / `title` / …）
3. 构建术语表（默认自动抽取）+ 跨块上下文
4. 经 OpenAI 兼容 LLM 翻译（非空校验 + 单条重试）
5. 用 PyMuPDF 遮盖原文，并在原 bbox 内重绘译文

目标语言固定为 **zh-CN**。

## 环境要求

```bash
export UNIPARSER_API_KEY="your-uniparser-key"   # 使用 --pages-tree 时可省略
export PDF_TRANSLATE_API_KEY="your-llm-key"     # 或 VQA_LLM_API_KEY / ARK_API_KEY
```

可选环境变量：


| 变量 | 用途 | 默认值 |
|------|------|--------|
| `UNIPARSER_API_KEY` | UniParser 解析 API Key | 在线解析时必填 |
| `UNIPARSER_BASE_URL` | UniParser 服务地址 | `https://uniparser.dp.tech` |
| `PDF_TRANSLATE_API_KEY` | 翻译用 LLM Key | 可回退 `VQA_LLM_API_KEY` / `ARK_API_KEY` |
| `PDF_TRANSLATE_BASE_URL` | LLM Base URL | Ark 默认 |
| `PDF_TRANSLATE_MODEL` | LLM 模型名 | Ark 默认 |
| `PDF_TRANSLATE_BATCH_SIZE` | 每批翻译单元数 | `12` |
| `PDF_TRANSLATE_MAX_WORKERS` | 并行翻译批次数 | `4` |


**不要**把 API Key 写进源码或提交进仓库。

## 命令行用法

```bash
# 解析 + 译成中文
uv run uniparser-agent translate ./paper.pdf -o ./translate_out --overwrite

# 复用已有 pages_tree
uv run uniparser-agent translate ./paper.pdf \
  --pages-tree ./parse/pages_tree.json \
  -o ./translate_out \
  --overwrite \
  --debug-layout

# 手动术语表（CSV：source,target[,tgt_lng]）；可关闭自动术语抽取
uv run uniparser-agent translate ./paper.pdf -o ./out --glossary ./terms.csv
uv run uniparser-agent translate ./paper.pdf -o ./out --no-auto-glossary
```

## 输出产物


| 文件 | 说明 |
|------|------|
| `translated.pdf` | 原位覆盖后的译文 PDF |
| `parse/pages_tree.json` | UniParser 版面树 |
| `translate_units.jsonl` | 逐块原文 / 译文 / 状态 |
| `run_meta.json` | 语言、模型、计数、耗时等元信息 |
| `llm_raw/` | LLM 原始回包与每次调用的 meta |
| `glossary_auto.json` | 自动抽取的术语表（开启时） |
| `glossary_auto.csv` | 同上，CSV 格式 |
| `layout_debug.pdf` | 可选：bbox 调试叠加层 |


## 质量门禁

- 拒绝空的 `translated_text`；兼容字段名 `translation` / `text`
- 批次不完整时对缺失单元单独重试（最多 2 次）
- 失败单元保留原文（不写空串、不盖白）
- 术语表只注入当前单元命中的词条
- 单元可带只读字段 `context_title` / `context_prev`（不要求模型翻译）

## 排版字号

字号按 UniParser **块类型固定**（不按 bbox 自适应缩放）：

| 类型 | 字号 (pt) |
|------|-----------|
| `documenttitle` | 16 |
| `title` | 12 |
| `paragraph` / `abstract` | 10 |
| `reference` / 各类 caption | 9 |

若固定字号下原文框放不下，会向下扩展绘制区域，**不缩小**该类型字号。

换行采用 CJK 友好策略（自定义断行 + `insert_text`），避免 `insert_textbox` 在中英混排时错误断词。

## 行内公式

UniParser 将行内公式存为 LaTeX，例如 `$ 55.00\% $`。翻译阶段保留该形式；**渲染时**再转为可读文本（如 `55.00%`、`β1`、`P1, …, PK`）。若正文字体缺少上下标字形，会回退为 `β1`、`10^-9` 等 ASCII 可读形式。

## MVP 限制

- 块级遮盖 + 重绘（非 BabelDOC 式字符级 content-stream 重建）
- 默认跳过公式块、表格、图片、页眉页脚等
- 目前仅支持本地 PDF（暂不支持仅 URL / 图片直接出 PDF）
- 过长译文可能溢出扩展后的框（状态 `overflow`），但仍保持类型字号

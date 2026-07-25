# 习题 VQA 抽取（`uniparser-agent vqa`）

从习题 / 试卷类 PDF（或图片、公开 PDF URL）中抽取结构化 VQA 问答对：题干、短答案、解析；若版面块带图片 `source`，会落盘并构成 **VQA** 训练样本（Markdown 图引用 + ShareGPT）。

解析使用 [UniParser](https://uniparser.dp.tech/)（默认 `SCIENTIFIC_PAPER_TRIGGER`，不单独改 figure 开关），问答抽取使用任意 **OpenAI 兼容** Chat Completions 接口（通过 `OPENAI_*` 配置）。

## 能做什么

- 输入本地 **PDF / 图片**，或公开 **PDF URL**
- 先调用 UniParser 得到版面树 `pages_tree.json`
- 将版面块整理为带 `id` 的内容列表（含可导出的配图），交给大模型按题号切分 QA
- 合并题干与答案/解析，输出：
  - `merged_vqa_pairs.jsonl`（结构化主结果，题干/解析可含 `![](vqa_images/...)`）
  - `merged_vqa_pairs.md`（人工阅读）
  - `vqa_images/`（从块 `source` 解码/拷贝的图片）
  - `vqa_sharegpt.json`（LLaMA-Factory 风格 `messages` + `images`）

已有 UniParser 解析结果时，可用 `--pages-tree` 跳过解析，只跑抽取（仍会从 tree 导出图片）。

本功能与化学分子/反应入库（`run` / `ingest`）相互独立，不写化学 SQLite 库。

## 环境要求

- Python 3.11+
- 已安装 `uniparser-agent`（见下方安装）
- **UniParser API Key**（主路径解析时需要，账户需有可用额度）
- **LLM 配置**：`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`（无内置默认）

## 安装

```bash
cd uniparser_agent
uv sync
```

或在已有虚拟环境中：

```bash
cd uniparser_agent
uv pip install -e ".[dev]"
```

## 配置

### 必填（按使用路径）

| 变量 | 何时需要 | 说明 |
|------|----------|------|
| `UNIPARSER_API_KEY` | 输入 PDF / 图片 / URL 时 | UniParser 云端解析 |
| `OPENAI_API_KEY` | 始终 | LLM API Key |
| `OPENAI_BASE_URL` | 始终 | OpenAI 兼容接口根地址（如 `.../v1`） |
| `OPENAI_MODEL` | 始终 | 模型名 |

```bash
export UNIPARSER_API_KEY="your-uniparser-key"
export OPENAI_API_KEY="your-llm-key"
export OPENAI_BASE_URL="http://192.168.198.191:8009/v1"   # 或其它兼容服务
export OPENAI_MODEL="Qwen3.5-397B-A17B-FP8"
```

也可在命令行覆盖：

```bash
uv run uniparser-agent vqa exam.pdf -o ./vqa_out \
  --api-key "$OPENAI_API_KEY" \
  --base-url "$OPENAI_BASE_URL" \
  --model "$OPENAI_MODEL"
```

### 可选

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `UNIPARSER_BASE_URL` | `https://uniparser.dp.tech` | UniParser 服务地址 |

## 快速开始

### 从 PDF 一键抽取

```bash
cd uniparser_agent
uv run uniparser-agent vqa /path/to/exam.pdf -o ./vqa_out --overwrite
```

成功后终端会打印合并题量，以及 JSONL / Markdown 路径。

### 题册 + 答案册双 PDF

题册与答案册分开时，先按「题册 → 答案册」合并为一个 PDF，再走一次 UniParser 与一次 LLM 抽取；配对仍由 `merge_vqa_pairs` 按题号 / 章节完成。

两侧都必须是**本地 PDF**（不支持 URL/图片与答案册混用；不可与 `--pages-tree` 同用）：

```bash
uv run uniparser-agent vqa /path/to/questions.pdf \
  --answer-pdf /path/to/answers.pdf \
  -o ./vqa_out \
  --overwrite
```

成功后输出目录会包含 `merge/merged.pdf`，`run_meta.json` 中 `parse.mode` 为 `dual_pdf`。

### 使用已有解析结果（跳过 UniParser）

适合解析已完成、或只想重跑 LLM 抽取时：

```bash
uv run uniparser-agent vqa \
  --pages-tree /path/to/pages_tree.json \
  -o ./vqa_out \
  --overwrite
```

此时不需要 `UNIPARSER_API_KEY`，仍需要 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`。

### 输入图片或公开 PDF URL

```bash
uv run uniparser-agent vqa /path/to/page.png -o ./vqa_out --overwrite
uv run uniparser-agent vqa "https://example.com/paper.pdf" -o ./vqa_out --overwrite
```

## 命令参数

```text
uniparser-agent vqa [OPTIONS] [INPUT_PATH]
```

| 参数 | 说明 |
|------|------|
| `INPUT_PATH` | 本地 PDF/图片路径，或公开 PDF URL；与 `--pages-tree` 二选一 |
| `-o` / `--output-dir` | 输出目录；默认当前目录下的 `vqa_out` |
| `--answer-pdf` | 答案册本地 PDF；与题册合并后再解析（不可与 `--pages-tree` 同用） |
| `--pages-tree` | 已有 `pages_tree.json` 路径，跳过 UniParser |
| `--overwrite` | 若输出目录已存在则清空重建 |
| `--json` | 向 stdout 打印机器可读的运行摘要 JSON |

查看帮助：

```bash
uv run uniparser-agent vqa --help
```

## 流水线说明

```text
PDF / 图片 / URL
    → UniParser 解析（或 --pages-tree）
    → pages_tree.json
    → 版面适配（去掉页眉页脚等噪声，公式块取 LaTeX；导出配图）
    → llm_content_list.json + vqa_images/
    → 大模型按块 id 切分 VQA
    → 解析并合并题干 / 答案 / 解析
    → merged_vqa_pairs.jsonl + .md
    → vqa_sharegpt.json
```

## 输出文件

默认写在 `-o` 指定目录下：

| 路径 | 含义 |
|------|------|
| `parse/pages_tree.json` | UniParser 版面树（主路径由解析生成；`--pages-tree` 时为拷贝） |
| `parse/*.md` 等 | 主路径下 UniParser 的 Markdown 与元数据（与 `parse` 命令一致） |
| `llm_content_list.json` | 带全局 `id` 的扁平内容列表，作为 LLM 输入（可含 `type:image`） |
| `llm_raw_response.txt` | 大模型原始回复（含 `<chapter>` / `<vqa_pair>` 与块 id） |
| `extracted_vqa.jsonl` | 按 id 还原文本后的 QA 片段（合并前） |
| `merged_vqa_pairs.jsonl` | **主结果**：合并后的问答对，一行一条 JSON |
| `merged_vqa_pairs.md` | 主结果的 Markdown 预览 |
| `vqa_images/` | 从 pages_tree 块 `source` 导出的配图文件 |
| `vqa_sharegpt.json` | ShareGPT 多模态样本：`messages` + `images`（绝对路径） |
| `run_meta.json` | 模型、耗时、题量、图片数、各文件路径等运行信息 |

### VQA / ShareGPT

- 默认 parse 模板下 `figure`/`chart` 可能关闭，**只有 tree 里实际带 `source` 的块才会进 `vqa_images/`**（如 molecule、部分 figure 子块等）。
- ShareGPT 中 user 消息对每张图前置一个 `<image>` 占位符，与 `images` 数组长度一致；assistant 为短答案 + 去图后的解析。
- 无图时 `images` 为空列表，退化为纯文本问答（无图），仍合法。

### `merged_vqa_pairs.jsonl` 字段

每行一个对象，常见字段：

| 字段 | 说明 |
|------|------|
| `label` | 题号（整数） |
| `question` | 题干（可含 LaTeX） |
| `answer` | 短答案（如选项字母、填空结果） |
| `solution` | 思路 / 解析等正文 |
| `question_chapter_title` / `answer_chapter_title` | 章节或栏目标题（若能抽到） |

日常使用优先查看 **`merged_vqa_pairs.jsonl`** 与 **`merged_vqa_pairs.md`**。

## 使用注意

- UniParser 账户需有足够额度，否则解析会失败；可先用 `uniparser-agent parse` 验证，或改用 `--pages-tree`。
- 大模型调用可能较久（试卷越长、公式越多越慢）；超时默认较长，适合批量离线跑。
- 输出目录已存在时必须加 `--overwrite`，否则会报错退出，避免误覆盖。
- 抽取质量依赖版面解析与模型；复杂公式粘连、跨页题目偶发切分不准时，可用 `llm_content_list.json` 与 `llm_raw_response.txt` 对照排查。

## 与其它命令的关系

| 命令 | 用途 |
|------|------|
| `uniparser-agent parse` | 只做 UniParser 解析 |
| `uniparser-agent vqa` | 解析（可选）+ 习题 VQA 抽取 |
| `uniparser-agent run` / `ingest` | 化学分子与反应建库（与 VQA 抽取无关） |

更完整的化学库用法见包根目录 [README_cn.md](../README_cn.md)。

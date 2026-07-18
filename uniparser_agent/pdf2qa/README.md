# 习题 QA 抽取（`uniparser-agent qa`）

从习题 / 试卷类 PDF（或图片、公开 PDF URL）中抽取结构化问答对：题干、短答案、解析，并落盘为 JSONL 与 Markdown，便于抽检与后续加工。

解析使用 [UniParser](https://uniparser.dp.tech/)，问答抽取默认使用火山引擎方舟（Ark）兼容的 Chat Completions 接口。

## 能做什么

- 输入本地 **PDF / 图片**，或公开 **PDF URL**
- 先调用 UniParser 得到版面树 `pages_tree.json`
- 将版面块整理为带 `id` 的内容列表，交给大模型按题号切分 QA
- 合并题干与答案/解析，输出：
  - `merged_qa_pairs.jsonl`（结构化主结果）
  - `merged_qa_pairs.md`（人工阅读）

已有 UniParser 解析结果时，可用 `--pages-tree` 跳过解析，只跑抽取。

本功能与化学分子/反应入库（`run` / `ingest`）相互独立，不写化学 SQLite 库。

## 环境要求

- Python 3.11+
- 已安装 `uniparser-agent`（见下方安装）
- **UniParser API Key**（主路径解析时需要，账户需有可用额度）
- **LLM API Key**（方舟 `ARK_API_KEY`，或统一用 `QA_LLM_API_KEY`）

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
| `ARK_API_KEY` 或 `QA_LLM_API_KEY` | 始终 | 大模型抽取；二者设其一即可（优先 `QA_LLM_API_KEY`） |

```bash
export UNIPARSER_API_KEY="your-uniparser-key"
export ARK_API_KEY="your-ark-key"
```

### 可选（LLM）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QA_LLM_BASE_URL` | `https://ark.cn-beijing.volces.com/api/v3` | OpenAI 兼容接口的 `base_url` |
| `QA_LLM_MODEL` | `glm-5-2-260617` | 模型或方舟推理接入点 ID |
| `UNIPARSER_BASE_URL` | `https://uniparser.dp.tech` | UniParser 服务地址 |

更换为其它 OpenAI 兼容服务时，同时设置 `QA_LLM_BASE_URL`、`QA_LLM_MODEL`，并用 `QA_LLM_API_KEY` 提供密钥即可。

（仍兼容旧环境变量名 `VQA_LLM_*`。）

## 快速开始

### 从 PDF 一键抽取

```bash
cd uniparser_agent
uv run uniparser-agent qa /path/to/exam.pdf -o ./qa_out --overwrite
```

成功后终端会打印合并题量，以及 JSONL / Markdown 路径。

### 使用已有解析结果（跳过 UniParser）

适合解析已完成、或只想重跑 LLM 抽取时：

```bash
uv run uniparser-agent qa \
  --pages-tree /path/to/pages_tree.json \
  -o ./qa_out \
  --overwrite
```

此时不需要 `UNIPARSER_API_KEY`，仍需要 LLM 密钥。

### 输入图片或公开 PDF URL

```bash
uv run uniparser-agent qa /path/to/page.png -o ./qa_out --overwrite
uv run uniparser-agent qa "https://example.com/paper.pdf" -o ./qa_out --overwrite
```

## 命令参数

```text
uniparser-agent qa [OPTIONS] [INPUT_PATH]
```

| 参数 | 说明 |
|------|------|
| `INPUT_PATH` | 本地 PDF/图片路径，或公开 PDF URL；与 `--pages-tree` 二选一 |
| `-o` / `--output-dir` | 输出目录；默认当前目录下的 `qa_out` |
| `--pages-tree` | 已有 `pages_tree.json` 路径，跳过 UniParser |
| `--overwrite` | 若输出目录已存在则清空重建 |
| `--json` | 向 stdout 打印机器可读的运行摘要 JSON |

查看帮助：

```bash
uv run uniparser-agent qa --help
```

## 流水线说明

```text
PDF / 图片 / URL
    → UniParser 解析（或 --pages-tree）
    → pages_tree.json
    → 版面适配（去掉页眉页脚等噪声，公式块取 LaTeX）
    → llm_content_list.json
    → 大模型按块 id 切分 QA
    → 解析并合并题干 / 答案 / 解析
    → merged_qa_pairs.jsonl + .md
```

## 输出文件

默认写在 `-o` 指定目录下：

| 路径 | 含义 |
|------|------|
| `parse/pages_tree.json` | UniParser 版面树（主路径由解析生成；`--pages-tree` 时为拷贝） |
| `parse/*.md` 等 | 主路径下 UniParser 的 Markdown 与元数据（与 `parse` 命令一致） |
| `llm_content_list.json` | 带全局 `id` 的扁平内容列表，作为 LLM 输入 |
| `llm_raw_response.txt` | 大模型原始回复（含 `<chapter>` / `<qa_pair>` 与块 id） |
| `extracted_qa.jsonl` | 按 id 还原文本后的 QA 片段（合并前） |
| `merged_qa_pairs.jsonl` | **主结果**：合并后的问答对，一行一条 JSON |
| `merged_qa_pairs.md` | 主结果的 Markdown 预览 |
| `run_meta.json` | 模型、耗时、题量、各文件路径等运行信息 |

### `merged_qa_pairs.jsonl` 字段

每行一个对象，常见字段：

| 字段 | 说明 |
|------|------|
| `label` | 题号（整数） |
| `question` | 题干（可含 LaTeX） |
| `answer` | 短答案（如选项字母、填空结果） |
| `solution` | 思路 / 解析等正文 |
| `question_chapter_title` / `answer_chapter_title` | 章节或栏目标题（若能抽到） |

日常使用优先查看 **`merged_qa_pairs.jsonl`** 与 **`merged_qa_pairs.md`**。

## 使用注意

- UniParser 账户需有足够额度，否则解析会失败；可先用 `uniparser-agent parse` 验证，或改用 `--pages-tree`。
- 大模型调用可能较久（试卷越长、公式越多越慢）；超时默认较长，适合批量离线跑。
- 输出目录已存在时必须加 `--overwrite`，否则会报错退出，避免误覆盖。
- 抽取质量依赖版面解析与模型；复杂公式粘连、跨页题目偶发切分不准时，可用 `llm_content_list.json` 与 `llm_raw_response.txt` 对照排查。

## 与其它命令的关系

| 命令 | 用途 |
|------|------|
| `uniparser-agent parse` | 只做 UniParser 解析 |
| `uniparser-agent qa` | 解析（可选）+ 习题 QA 抽取 |
| `uniparser-agent run` / `ingest` | 化学分子与反应建库（与 QA 抽取无关） |

更完整的化学库用法见包根目录 [README_cn.md](../README_cn.md)。

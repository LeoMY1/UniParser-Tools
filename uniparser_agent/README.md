# UniParser Agent

UniParser Agent 是基于 UniParser 的文档处理包，提供统一的命令行入口：

- `parse`：将 PDF、图片或公开 PDF URL 解析为结构化文档。
- `vqa`：从习题、试卷、题册或答案册中提取题目、答案、解析和相关图片，并生成结构化 VQA 数据。

本包包含文档解析、LLM 调用和 pdf2vqa 流程所需的公共模块。

安装方式、配置说明、命令参数、处理流程和输出格式，请参阅：

- [pdf2vqa 完整文档](pdf2vqa/README.md)
- [pdf2vqa Agent Skill](skills/pdf2vqa/SKILL.md)（使用前必须先安装本 `uniparser-agent` 项目）

## 面向 AI Agent

本项目提供 **pdf2vqa Agent Skill**，用于将习题、试卷、题库和答案册转换为包含题干、短答案、解析、公式和相关图片的结构化 VQA 数据。Skill 使用当前 Agent 完成推理，由 `uniparser-agent` 负责文档解析、分块、响应校验、问答配对和结果导出，不调用 `OPENAI_*` 配置的外部模型。

### 快速使用 pdf2vqa Skill

**1. 安装 uniparser-agent**

先按 [pdf2vqa 完整文档](pdf2vqa/README.md#安装)安装本项目，并确认命令可用：

```bash
uniparser-agent --help
```

**2. 安装 Skill**

安装 CLI 不会自动注册 Skill。请将 [skills/pdf2vqa/](skills/pdf2vqa/) 整个目录安装到 Agent 的 Skills 目录，重启 Agent，并确认 Skill 列表中出现 **pdf2vqa**。

**3. 准备 UniParser API Key**

输入原始 PDF、图片或公开 PDF URL 时，需要设置 UniParser API Key：

```bash
export UNIPARSER_API_KEY="your-api-key"
```

使用已有 `pages_tree.json` 时不需要该 Key。不要把真实 API Key 写入源码或提交到仓库。

**4. 在 Agent 中使用 Skill**

支持单个 PDF、题册与答案册两个独立 PDF、本地图片、公开 PDF URL 和已有 `pages_tree.json`。在对话中提供文件或路径，并提出类似请求即可：

- `使用 pdf2vqa 提取这个试卷`
- `使用这个问题 PDF 和答案 PDF 生成 VQA`
- `使用 pages_tree.json 重新提取 VQA`
- `输出到指定目录，执行前先告诉我目录`

Skill 会使用明确的输出目录；长任务开始前会先告知目录，用户要求确认时会等待确认后执行。

**5. 查看输出结果**

完成后，Agent 会报告输出目录、问答对数量、缺失字段和可见的不确定项。主要文件包括：

| 文件 | 用途 |
| --- | --- |
| `merged_vqa_pairs.jsonl` | 结构化完整问答对 |
| `merged_vqa_pairs.md` | 便于人工预览和检查的 Markdown |
| `vqa_sharegpt.json` | ShareGPT 格式的模型训练数据 |
| `vqa_images/` | 题目和解析引用的图片 |
| `run_meta.json` | 题量、图片数、耗时和运行路径 |
| `llm_raw_response.txt` | 完整推理审计记录 |

**6. 使用边界**

- Skill 模式不读取或调用 `.env` 中配置的外部 LLM。
- 原始 PDF、图片或 URL 仍需通过 UniParser 解析。
- Agent 会按顺序处理全部请求块，通过校验后再生成最终结果。
- 抽取准确性受原始解析质量和文档结构影响，正式入库或训练前建议抽样检查。

Agent 执行步骤见 [SKILL.md](skills/pdf2vqa/SKILL.md)，响应格式与输出契约见 [output-contract.md](skills/pdf2vqa/references/output-contract.md)，CLI 参数和完整输出说明见 [pdf2vqa 完整文档](pdf2vqa/README.md)。

# CN 化学专利结构化提取（`uniparser-agent`）

Chemistry 当前只保留一条 V2 数据链路：将 CN 化学专利的 UniParser
`pages_tree.json` 划分为三个导航节点，再生成专利基本信息和 Markush 通式分析产物。

```text
PDF / 图片 / URL
→ UniParser pages_tree
→ CN 专利三节点语义树
├─ 首页 → 规则提取专利基本信息
├─ 权利要求书（当前不做字段提取）
└─ 说明书
   → markush=true 结构清单
   → 通式公开记录
   → 锚点任务包
   → 有限轮检索 Agent（提取字段 + 对象分类）
   → 简化证据账本
   → 保守去重与正式表过滤
→ JSON + 结构图 + Excel
```

旧版全文固定分块 LLM、Strategy A enrichment、SQLite 分子库和 CSV 导出链路已经移除。

## 当前支持范围

- 只支持 CN 专利语义结构。
- 语义树只负责区分：

  ```text
  专利
  ├─ 首页
  ├─ 权利要求书
  └─ 说明书
  ```

- 专利基本信息只通过首页导航节点进行规则提取，不调用 LLM。
- 在整个说明书中收集 UniParser 返回的 `type=molecule, markush=true`。
- 原始结构清单按原始 SMI 精确去重；相同结构使用不同通式编号公开时，拆成不同通式记录。
- LLM 以通式锚点组成任务包，并按需检索整个说明书，不再顺序扫描固定分块。
- 对象分类复用同一次 LLM 调用，不单独增加分类调用。正式表只保留通式和合成路线中的通用结构；
  取代基选项、绘图规则、固定化合物、试剂/催化剂会留在证据账本但不进入正式表。
- 代码只自动合并同一原始结构下的等价名称，或唯一且不增加定义范围的无名副本；
  `Ia`、`Ia′`、`Ib` 等不同非空名称不会自动合并。
- 每个非空 LLM 字段都必须引用当前上下文中的证据单元；不生成、修复或标准化 SMILES。
- 保留 UniParser 原始结构图，并嵌入通式分析 Excel。
- 分子和反应式解析模式在 Agent 入口固定为 `ocr-fast`。

当前不做权利要求细分、具体化合物表、代表性实施例化合物表、关键中间体表，
也不做反应式结构化入库。

## 通式 Agent 的 MVP 边界

| 参数 | 固定值 |
|---|---:|
| 单次上下文上限 | 12,000 字符 |
| 相邻扩展重叠 | 800 字符 |
| 单任务包最多通式 | 20 个 |
| 相邻锚点最大间距 | 3,000 字符 |
| 任务包锚点最大跨度 | 8,000 字符 |
| 每任务包最多轮数 | 4 轮 |
| 搜索结果每页 | 5 个 |
| 搜索最多页数 | 4 页 |
| JSON 解析重试 | 2 次 |
| LLM temperature | 0 |

检索工具只有三类：查找同一通式的其他出现位置、按原文短语搜索、向前或向后扩展上下文。
连续两个不同检索动作都没有新增证据时提前停止，避免无效消耗。

## 配置

从 PDF、图片或 URL 开始时需要 UniParser 配置；已有 `pages_tree.json`
时可以直接运行 `ingest`。

| 变量 | 用途 |
|---|---|
| `UNIPARSER_API_KEY` | 调用 UniParser 解析服务 |
| `OPENAI_API_KEY` | 总结 Markush 通式定义 |
| `OPENAI_BASE_URL` | OpenAI 兼容服务地址 |
| `OPENAI_MODEL` | LLM 模型名 |

不配置 `OPENAI_*` 或使用 `--skip-llm` 时，仍会生成语义树、基本信息、Markush
清单、任务包、结构图和 Excel。由于候选没有完成对象分类，它们会在证据账本中标为待复核，
不会直接进入正式通式表。

## 使用

### 从原始文档开始

```bash
uv run uniparser-agent run /path/to/patent.pdf \
  --doc-id CN115974847A \
  --output-dir /path/to/output
```

### 从已有 pages_tree 开始

```bash
uv run uniparser-agent ingest /path/to/pages_tree.json \
  --doc-id CN115974847A \
  --output-dir /path/to/output
```

### 只生成规则结果

```bash
uv run uniparser-agent ingest /path/to/pages_tree.json \
  --doc-id CN115974847A \
  --skip-llm
```

也可以单独运行：

```bash
uv run uniparser-agent patent-structure /path/to/pages_tree.json
uv run uniparser-agent patent-basic-info /path/to/pages_tree.json
uv run uniparser-agent patent-general-formulas /path/to/pages_tree.json
```

## 输出

`run` 和 `ingest` 会生成：

- `patent_structure.json`
- `patent_basic_info.json`
- `markush_inventory.json`
- `formula_task_packets.json`
- `formula_evidence_ledger.json`
- `formula_agent_contexts.json`
- `general_formula_analysis.json`
- `general_formula_analysis.xlsx`
- `general_formula_extraction_summary.json`
- `structure_images/<DOC_ID>/`

其中，任务包用于复现实验参数，证据账本保留每个候选的分类、表格处理动作和字段证据；
Agent 上下文文件保留每轮实际送入模型的说明书文本和检索轨迹。

每次运行都会根据当前 `pages_tree.json` 重新构建语义树，不复用旧版语义树缓存。

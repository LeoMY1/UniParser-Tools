# CN 化学专利结构化提取（`uniparser-agent`）

当前 Chemistry 只保留一条 V2 数据链路：把 CN 化学专利的 UniParser
`pages_tree.json` 划分为固定语义结构，并生成专利基本信息和 Markush
通式分析产物。

```text
PDF / 图片 / URL
→ UniParser pages_tree
→ CN 专利语义树
├─ 首页 → 专利基本信息
└─ 说明书
   ├─ 发明内容 → LLM 总结通式定义
   └─ 具体实施方式
→ JSON + 结构图 + Excel
```

旧版全文分子扫描、Strategy A enrichment、SQLite 分子库和 CSV 导出链路已经移除。

## 当前支持范围

- 只支持 CN 专利语义结构。
- 语义树固定为：

  ```text
  专利
  ├─ 首页
  ├─ 权利要求书
  └─ 说明书
     ├─ 发明内容
     └─ 具体实施方式
  ```

- 专利基本信息只通过首页导航节点进行规则提取，不调用 LLM。
- 在整个说明书中收集 UniParser 返回的 `type=molecule, markush=true`，
  按原始 SMI 精确去重，建立通式清单。
- LLM 上下文只来自“说明书 → 发明内容”，按约 12,000 字符切块，
  重叠 800 字符。
- 保留 UniParser 原始结构图，并嵌入通式分析 Excel。
- 分子和反应式解析模式在 Agent 入口固定为 `ocr-fast`。

当前不做权利要求细分、具体化合物表、代表性实施例化合物表、关键中间体表，
也不做反应式结构化入库。

## 配置

从 PDF、图片或 URL 开始时需要 UniParser 配置；已有 `pages_tree.json`
时可以直接运行 `ingest`。

| 变量 | 用途 |
|---|---|
| `UNIPARSER_API_KEY` | 调用 UniParser 解析服务 |
| `OPENAI_API_KEY` | 总结 Markush 通式定义 |
| `OPENAI_BASE_URL` | OpenAI 兼容服务地址 |
| `OPENAI_MODEL` | LLM 模型名 |

不配置 `OPENAI_*` 或使用 `--skip-llm` 时，仍会生成语义树、基本信息、
Markush 清单、结构图和 Excel，只是不补充通式名称、角色及可变基团定义。

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
- `formula_context_chunks.json`
- `general_formula_analysis.json`
- `general_formula_analysis.xlsx`
- `general_formula_extraction_summary.json`
- `structure_images/<DOC_ID>/`

每次运行都会根据当前 `pages_tree.json` 重新构建语义树，不复用旧版语义树缓存。

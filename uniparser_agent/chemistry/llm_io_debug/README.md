# llm_io_debug（开发调试专用）

独立调试包：跑分子 enrich 时把每批 LLM 的 **system / user / 原始回复** 落到磁盘，方便对照摘要错误。

**测完可整夹删除本目录**，不影响正式 `run` / `ingest`。

## 产物路径

默认：

`/root/code/test/chemistry/llm_io_debug/{doc_id}/link_000.json`（关联）
`/root/code/test/chemistry/llm_io_debug/{doc_id}/sum_000.json`（总结）
`/root/code/test/chemistry/llm_io_debug/{doc_id}/act_000.json`（活性表）

该路径在 `/root/code/test/` 下（不在 UniParser-Tools 仓库内）。`/root/code/test/.gitignore` 已忽略 `chemistry/llm_io_debug/`，**不要**把产物拷进正式仓库提交。

## 用法（CN106 示例）

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=...
export OPENAI_MODEL=...

cd /root/code/UniParser-Tools/uniparser_agent
uv run python -m uniparser_agent.chemistry.llm_io_debug.run_dump \
  /root/code/test/chemistry/pages_tree.json \
  --doc-id CN106380440B
```

查看：

```bash
ls /root/code/test/chemistry/llm_io_debug/CN106380440B/
```

可选写库：

```bash
uv run python -m uniparser_agent.chemistry.llm_io_debug.run_dump \
  /root/code/test/chemistry/pages_tree.json \
  --doc-id CN106380440B \
  --db /root/code/test/chemistry/chemistry.db
```

自定义产物根目录：`--out /path/to/dir`（默认仍是 `/root/code/test/chemistry/llm_io_debug`）。

## 清理

```bash
rm -rf /root/code/UniParser-Tools/uniparser_agent/chemistry/llm_io_debug
rm -rf /root/code/test/chemistry/llm_io_debug
```

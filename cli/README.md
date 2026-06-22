# UniParser CLI 使用说明

`uniparser` 是 UniParser 的命令行工具，用于把 PDF、图片或公网 PDF 链接解析成 Markdown，并保存到本地目录。

官网与 API Key 申请：[https://uniparser.dp.tech/](https://uniparser.dp.tech/)

---

## 安装

在仓库根目录执行（**必须**用这一条，才会安装 `uniparser` 命令）：

```bash
cd /path/to/UniParser-Tools
pip install -e .
```

> 只运行 `pip install -r requirements.txt` **不会**出现 `uniparser` 命令。

检查是否安装成功：

```bash
uniparser --help
```

---

## 快速开始

**第一次使用：配置 API Key**

```bash
uniparser auth
```

按提示在 [https://uniparser.dp.tech/](https://uniparser.dp.tech/) 获取 Key 并粘贴保存。配置会写入 `~/.uniparser/config.yaml`，下次无需重复输入。

**解析一个 PDF**

```bash
uniparser parse /path/to/report.pdf
```

默认把结果保存到：

```text
~/Uni-Parser-Skill/report/
├── report.md           # 解析后的 Markdown
├── pages_tree.json     # 文档版面结构（可选查阅）
└── trigger_meta.json   # 任务信息（含 token，便于中断后恢复）
```

终端会显示 `Parsing... report.pdf`，完成后打印 Markdown 与输出目录路径。

---

## 命令一览

| 命令 | 作用 |
|------|------|
| `uniparser auth` | 配置 / 查看 API Key |
| `uniparser parse INPUT` | 解析文件或 PDF 链接 |
| `uniparser fetch --token TOKEN` | 用已有任务 token 重新下载结果 |
| `uniparser health` | 检查服务是否可用 |
| `uniparser version` | 查看工具版本 |

---

## 配置 API Key

### 交互式配置（推荐）

```bash
uniparser auth
```

已有 Key 时直接回车可保留当前配置。

### 其他方式

也可任选其一（优先级从高到低）：

1. 命令行临时指定：`uniparser --api-key YOUR_KEY parse file.pdf`
2. 环境变量：`export UNIPARSER_API_KEY="YOUR_KEY"`
3. 配置文件：`~/.uniparser/config.yaml`（由 `uniparser auth` 写入）

### 查看与检查

```bash
uniparser auth --show      # 查看 Key 来源与脱敏后的 Key
uniparser auth --verify    # 检查是否已配置（不联网校验）
```

---

## 解析文档：`parse`

### 基本用法

```bash
# 本地 PDF
uniparser parse paper.pdf

# 本地图片（png、jpg、webp 等）
uniparser parse figure.png

# 公网 PDF 链接
uniparser parse https://example.com/paper.pdf
```

### 常用选项

| 选项 | 说明 |
|------|------|
| `-o` / `--output-dir DIR` | 指定输出目录（默认 `~/Uni-Parser-Skill/<文件名>/`） |
| `--overwrite` | 输出目录已存在时，先清空再写入 |
| `--async` | 异步提交任务（适合较大文档） |

示例：

```bash
uniparser parse paper.pdf -o ./results/
uniparser parse paper.pdf -o ./results/ --overwrite
```

### 输出说明

解析成功后，输出目录中通常包含：

| 文件 | 用途 |
|------|------|
| `<文件名>.md` | 完整 Markdown 正文（主要结果） |
| `pages_tree.json` | 版面结构树，便于按章节/块定位 |
| `trigger_meta.json` | 任务 token 与输入信息，供 `fetch` 恢复使用 |

解析过程中终端会显示一行 `Parsing... <文件名>`。大文档可能需要等待数分钟。

---

## 恢复下载：`fetch`

若解析中断，或你已有任务 token，可用 `fetch` 继续拉取结果（不会重新上传文件）：

```bash
uniparser fetch --token YOUR_TOKEN
```

token 可在上次 `parse` 输出目录的 `trigger_meta.json` 中找到。

| 选项 | 说明 |
|------|------|
| `-o` / `--output-dir DIR` | 指定输出目录（默认 `~/Uni-Parser-Skill/token_<前8位>/`） |
| `--overwrite` | 输出目录已存在时，先清空再写入 |

```bash
uniparser fetch --token abcdef1234567890 -o ./out/
```

---

## 其他命令

### 检查服务

```bash
uniparser health
```

需要已配置 API Key。

### 查看版本

```bash
uniparser version
```

未配置 API Key 时仍会显示本地工具版本；配置后可同时查看远端服务版本。

---

## 脚本与自动化：`--json`

在命令**最前面**加上 `--json`，成功时会在标准输出打印 JSON，便于脚本解析：

```bash
uniparser --json parse paper.pdf
uniparser --json fetch --token YOUR_TOKEN
```

注意：`--json` 必须写在子命令**之前**：

```bash
uniparser --json parse paper.pdf    # 正确
uniparser parse paper.pdf --json    # 错误
```

---

## 常见问题

**提示 `No API key found`**

运行 `uniparser auth`，或设置环境变量 `UNIPARSER_API_KEY`。

**提示 `File not found`**

检查 `parse` 后的文件路径是否正确（建议使用绝对路径）。

**提示输出目录已存在**

加上 `--overwrite`，或换用 `-o` 指定新目录。

**命令 `uniparser` 找不到**

确认已执行 `pip install -e .`，且与当前终端使用的是同一 Python 环境。

**解析时间较长**

属正常现象；请等待 `Parsing...` 出现后保持终端不要关闭。若中断，用 `trigger_meta.json` 中的 token 执行 `uniparser fetch`。

---

## 推荐使用流程

```bash
# 1. 安装并配置
pip install -e .
uniparser auth

# 2. 解析
uniparser parse ~/Documents/paper.pdf

# 3. 打开结果
open ~/Uni-Parser-Skill/paper/paper.md
```

若需中断后恢复：

```bash
# 从 trigger_meta.json 复制 token
uniparser fetch --token <token>
```

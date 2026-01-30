# UniParser-Tools

UniParser Tools 是一个强大的文档解析工具包，支持对 PDF 文件和图片进行智能解析，提取文本、表格、图片、公式、分子结构等多种语义元素。

本工具包提供了完整的 Python API，方便开发者快速集成文档解析能力到自己的项目中。

## 主要功能

### 核心解析能力

- **文本提取 textual**：支持数字导出和 OCR 快速识别
- **表格识别 table**：自动识别表格结构并提取内容
- **公式识别 equation**：识别数学公式和化学表达式
- **分子识别 molecule**：提取化学分子式及其索引
- **反应式识别 expression**：提取化学反应式
- **图表识别 chart**：识别简单图表元素
- **图片识别 figure**：提取图片

### 输出格式

支持多种输出格式，满足不同场景需求：

- **Content (End2End)**：全文文本内容，适用于 LLM 等场景
- **Objects**：JSON 格式的语义块，适用于语义分析
- **Pages dict**：原始解析格式，按页面组织的详细语义块
- **Pages tree**：带嵌套关系的树结构，支持复杂语义分析

### 格式化输出

支持多种格式化输出方式：

- **Markdown**：Markdown 格式输出 ⭐️
- **HTML**：HTML 格式输出 ⭐️
- **LaTeX**：LaTeX 格式输出
- **Plain**：纯文本格式输出
- **Markup**：标记文本格式输出

### 高级功能

- **图文对提取**：自动提取图片及其对应的标题、图注
- **表格结构化提取**：提取表格及其表题、表注
- **分子索引关联**：提取分子结构及其索引信息
- **公式索引关联**：提取公式及其编号信息

## 安装

```bash
pip install -r requirements.txt
```

或者安装为可编辑包：

```bash
pip install -e .
```

## 快速开始

> ‼️‼️‼️ 以下仅为代码功能示例，具体运行代码请参考 `playground/*.ipynb` ‼️‼️‼️

### 1. 初始化客户端

```python
import os
from uniparser_tools.api.clients import UniParserClient

# 设置 API 密钥
api_key = os.getenv('UNIPARSER_API_KEY')

# 初始化客户端
parser = UniParserClient(
    host="https://uniparser.dp.tech/",
    api_key=api_key
)
```

### 2. 解析 PDF 文件

```python
from uniparser_tools.common.constant import ParseMode, ParseModeTextual

# 提交解析任务
result = parser.trigger_file(
    pdf_path="./example.pdf",
    textual=ParseModeTextual.DigitalExported,
    table=ParseMode.OCRFast,
    molecule=ParseMode.OCRFast,
    chart=ParseMode.DumpBase64,
    figure=ParseMode.DumpBase64,
    expression=ParseMode.DumpBase64,
    equation=ParseMode.OCRFast,
)

if result["status"] == "success":
    token = result["token"]
    print(f"解析成功，token: {token}")
```

### 3. 获取解析结果

```python
from uniparser_tools.common.constant import FormatFlag

# 获取 Markdown 格式的全文内容
result = parser.get_formatted(
    token,
    content=True,
    textual=FormatFlag.Markdown,
    table=FormatFlag.Markdown,
    equation=FormatFlag.Markdown,
)

if result["status"] == "success":
    print(result["content"])
```

### 4. 解析图片文件

```python
from uniparser_tools.common.constant import ParseMode, ParseModeTextual

# 提交图片解析任务
result = parser.trigger_snip(
    snip_path="./example.png",
    textual=ParseModeTextual.OCRFast,
    table=ParseMode.OCRFast,
    molecule=ParseMode.OCRFast,
)

if result["status"] == "success":
    token = result["token"]
    # 使用 token 获取解析结果
```

## 使用示例

### 图文对提取

详细示例请参考 `playground/app.caption_extraction.ipynb`：

```python
import json
import os
from uniparser_tools.tools.caption_extraction.main import main

# 设置文件路径和保存目录
pdf_path = "./example.pdf"
save_dir = "./outputs/caption_extraction"
os.makedirs(save_dir, exist_ok=True)

# 首先需要提交解析任务并获取 token（参考前面的步骤）
# result = parser.trigger_file(pdf_path, ...)
# token = result["token"]

# 获取解析结果
result = parser.get_result(token, pages_dict=True)
json_path = f"{save_dir}/{token}.json"
json.dump(result["pages_dict"], open(json_path, "w"), indent=4)

# 提取图文对
results = main(
    token=token,
    pdf_path=pdf_path,
    json_path=json_path,
    save_dir=save_dir,
    dpi=300,
    log_level="INFO",
)

# 处理提取结果
if results:
    extracted = results["extracted"]
    for k, item in extracted.items():
        # item.main_image: 主图片
        # item.caption_image: 图题图片
        # item.group_image: 组合图片
        # item.captions: 图题文本列表
        # item.keywords: 关键词列表
        pass
```

### 多种格式输出

可以在同一次格式化输出中设置不同语义元素的输出模式：

```python
from uniparser_tools.common.constant import FormatFlag

# token 和 parser 需要从前面的步骤获取
result = parser.get_formatted(
    token,
    content=True,
    textual=FormatFlag.Markdown,    # 文本使用 Markdown
    table=FormatFlag.Html,          # 表格使用 HTML
    equation=FormatFlag.Latex,       # 公式使用 LaTeX
)

if result["status"] == "success":
    print(result["content"])
```

## 项目结构

```
uniparser_tools/
├── api/              # API 客户端
├── common/           # 通用常量和数据类
├── tools/            # 工具模块
│   └── caption_extraction/  # 图文对提取工具
├── utils/            # 工具函数
└── order/            # 排序算法

playground/
├── 01.quick_start.ipynb          # 快速开始教程
├── 02.advance.ipynb              # 高级用法教程
├── app.caption_extraction.ipynb  # 图文对提取示例
└── app.molecule_extracrtion.ipynb # 分子提取示例
```

## 详细文档

项目提供了丰富的示例和教程，位于 `playground/` 目录下：

- **快速开始**：`playground/01.quick_start.ipynb` - 基础用法教程，包括 PDF 和图片解析、多种格式输出
- **高级用法**：`playground/02.advance.ipynb` - 高级功能教程，包括图片+图题+图注、表格+表题+表注、分子+分子索引、公式+公式索引的提取
- **图文对提取**：`playground/app.caption_extraction.ipynb` - 图文对提取完整示例
- **分子提取**：`playground/app.molecule_extracrtion.ipynb` - 分子结构提取示例

## 注意事项

1. **并发限制**：公开 UniParser 服务最高仅允许 5 并发，使用时请注意控制并发数量
2. **API 密钥**：需要配置有效的 API 密钥才能使用服务，可通过环境变量 `UNIPARSER_API_KEY` 设置
3. **服务端点**：不同 host 对应功能不完全相同，解析质量也不一样，具体请在售后群中咨询
4. **图文对提取**：必须使用特定端口（30001）进行解析，其他接口不支持提取图文对
5. **Token 复用**：解析任务提交后会返回一个 token，可以持有该 token 多次获取不同格式的结果

## 依赖要求

主要依赖包请参考 `requirements.txt`，包括：

- PyMuPDF
- pandas
- pillow
- opencv-python
- numpy
- scipy
- lxml
- 等

## 许可证

[待补充]

## 联系方式

如有问题，请在售后群中咨询。

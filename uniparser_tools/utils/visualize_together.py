#!/usr/bin/env python3
# coding: utf-8

import html
import io
import json
import re
from dataclasses import asdict, fields, is_dataclass
from typing import Any, Dict, List, Optional, Union

import fitz  # PyMuPDF
from PIL import Image

from uniparser_tools.common.constant import LayoutType
from uniparser_tools.common.dataclass import (
    BBox,
    ChartResult,
    EquationResult,
    ExpressionResult,
    FigureResult,
    GroupedResult,
    LayoutItem,
    MoleculeResult,
    SemanticItem,
    TabularResult,
    TextualResult,
)
from uniparser_tools.utils.image import dump_image_base64_str


def safe_instantiate(cls, data: Dict[str, Any]):
    if not is_dataclass(cls):
        return cls(**data)
    valid_fields = {f.name for f in fields(cls)}
    filtered_data = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**filtered_data)


def build_item(block: Union[Dict, SemanticItem]) -> SemanticItem:
    if not isinstance(block, dict):
        return block

    data = block.copy()
    if "pages" in data:
        data.pop("pages")

    if "items" in data:
        data["items"] = [build_item(child) for child in data["items"]]

    type_str = data.get("type", "").lower() if isinstance(data.get("type"), str) else ""

    if "reactions" in data or type_str == "expression":
        return safe_instantiate(ExpressionResult, data)
    elif "placeholders" in data or "structure" in data or type_str == "table":
        if "html" in data and "structure" not in data:
            data["structure"] = data.pop("html")
        if "text" in data:
            data.pop("text", None)
        return safe_instantiate(TabularResult, data)
    elif "markush" in data or type_str == "molecule":
        return safe_instantiate(MoleculeResult, data)
    elif "data" in data or type_str == "chart":
        return safe_instantiate(ChartResult, data)
    elif "desc" in data or type_str == "figure":
        return safe_instantiate(FigureResult, data)
    elif "latex_repr" in data or type_str == "equation":
        return safe_instantiate(EquationResult, data)
    elif "text" in data or type_str in [
        "text",
        "title",
        "section",
        "caption",
        "list",
        "index",
        "equationid",
        "moleculeid",
    ]:
        return safe_instantiate(TextualResult, data)
    elif "items" in data:
        return safe_instantiate(GroupedResult, data)
    else:
        return safe_instantiate(LayoutItem, data)


def flatten_semantic_items_obj(item: SemanticItem) -> List[SemanticItem]:
    res = [item]
    if isinstance(item, GroupedResult):
        for child in item.items:
            res.extend(flatten_semantic_items_obj(child))
    return res


LABEL_COLORS = {
    # Top-level layout types
    LayoutType.DocumentTitle.value: "#1f77b4",  # 文档标题
    LayoutType.Title.value: "#ff7f0e",  # 章节标题
    LayoutType.Paragraph.value: "#2ca02c",  # 段落（文本）
    LayoutType.KeyValue.value: "#d62728",  # 字段代码（专利）
    LayoutType.Reference.value: "#9467bd",  # 参考文献
    LayoutType.Table.value: "#8c564b",  # 表格
    LayoutType.TableCaption.value: "#e377c2",  # 表格标题
    LayoutType.TableFootnote.value: "#7f7f7f",  # 表格脚注
    LayoutType.Image.value: "#bcbd22",  # 图像
    LayoutType.ImageCaption.value: "#17becf",  # 图像标题
    LayoutType.ImageFootnote.value: "#084f8f",  # 图像脚注
    LayoutType.Equation.value: "#cc6600",  # 公式（数学公式）
    LayoutType.EquationID.value: "#1b7a1b",  # 公式编号
    LayoutType.Algorithm.value: "#006bb3",  # 算法
    LayoutType.AlgorithmCaption.value: "#ff9933",  # 算法标题
    LayoutType.AlgorithmFootnote.value: "#40d040",  # 算法脚注
    LayoutType.TOC.value: "#cc6600",  # 目录
    LayoutType.Group.value: "#a61e1f",  # 组合
    LayoutType.HLine.value: "#6b4a8a",  # 分割
    LayoutType.PageHeader.value: "#634033",  # 页眉
    LayoutType.PageFooter.value: "#b35d9a",  # 页脚
    LayoutType.PageNumber.value: "#595959",  # 页码
    LayoutType.PageBar.value: "#858818",  # 页栏
    LayoutType.PageNote.value: "#108a97",  # 页注
    LayoutType.Watermark.value: "#3a9fdf",  # 水印（其他）
    # Bottom-level layout types
    LayoutType.Molecule.value: "#ffb84d",  # 内联分子
    LayoutType.MoleculeID.value: "#3fd03f",  # 内联分子索引
    LayoutType.MoleculeGroup.value: "#ff5c5d",  # 内联分子组
    LayoutType.Figure.value: "#b084d9",  # 内联图像
    LayoutType.Expression.value: "#b57b6c",  # 内联反应式
    LayoutType.Chart.value: "#f5a5d8",  # 内联图表
    LayoutType.Legend.value: "#a6a6a6",  # 内联子图图例
    LayoutType.FigureCaption.value: "#d4d52a",  # 内联子图标题
    LayoutType.FigureGroup.value: "#20e1f2",  # 内联图组
}

mapping_class = {
    LayoutType.Description: LayoutType.TableFootnote,
    LayoutType.Text: LayoutType.Paragraph,
    LayoutType.Figure: LayoutType.Image,
    LayoutType.Token: LayoutType.MoleculeID,
    LayoutType.Caption: LayoutType.ImageCaption,
}

for t in LayoutType:
    if t.value not in LABEL_COLORS:
        LABEL_COLORS[t.value] = "#7B8185"


def get_mapped_category(item: SemanticItem) -> str:
    orig_type = getattr(item, "type", None)
    mapped_type = mapping_class.get(orig_type, orig_type)
    if hasattr(mapped_type, "value"):
        return str(mapped_type.value)
    return str(mapped_type)


HTML_TMPL = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect width=%22100%22 height=%22100%22 rx=%2220%22 fill=%22%233b82f6%22/><rect x=%2225%22 y=%2225%22 width=%2250%22 height=%2210%22 rx=%223%22 fill=%22%23ffffff%22/><rect x=%2225%22 y=%2245%22 width=%2235%22 height=%2210%22 rx=%223%22 fill=%22%23ffffff%22/><rect x=%2225%22 y=%2265%22 width=%2250%22 height=%2210%22 rx=%223%22 fill=%22%23ffffff%22/><path d=%22M20 40 L65 40 L65 60 L20 60 Z%22 fill=%22none%22 stroke=%22%23fde047%22 stroke-width=%224%22 stroke-dasharray=%226,4%22/></svg>">
<style>
/* CSS 基础样式 */
html, body {{ height:100%; margin:0; padding:0; overflow:hidden; }}
body {{ font-family: "Segoe UI", "Roboto", "Helvetica Neue", Arial, sans-serif; background: #f8fafc; color: #333; }}

/* 顶部导航栏整体美化 */
.info_header {{ display:flex; align-items:center; justify-content:space-between; padding:0 24px; height: 60px; background:#ffffff; border-bottom:1px solid #eef2f6; box-shadow: 0 2px 10px rgba(0,0,0,0.03); flex-shrink: 0; z-index: 10; }}
.header-left {{ display: flex; align-items: center; gap: 20px; }}
.header-logo {{ font-size: 18px; font-weight: 800; color: #1e293b; letter-spacing: 0.5px; border-right: 2px solid #e2e8f0; padding-right: 20px; display: flex; align-items: center; gap: 8px; }}
.header-logo span {{ color: #3b82f6; }}

/* 文档标题与页码的美化块 */
.doc-info {{ display: flex; align-items: center; gap: 12px; background: #f8fafc; padding: 6px 16px; border-radius: 8px; border: 1px solid #e2e8f0; }}
.doc-icon {{ font-size: 16px; }}
.doc-name {{ font-size: 14px; font-weight: 600; color: #334155; }}
.page-badge {{ font-size: 12px; font-weight: 700; color: #2563eb; background: #dbeafe; padding: 4px 10px; border-radius: 20px; letter-spacing: 0.3px; }}

/* 右上角上传框样式 */
.header-right {{ display: flex; align-items: center; }}
.upload-header-btn {{ display: flex; align-items: center; gap: 8px; padding: 8px 18px; background-color: #eff6ff; border: 1px dashed #3b82f6; border-radius: 8px; color: #2563eb; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s ease; }}
.upload-header-btn svg {{ width: 18px; height: 18px; stroke: #2563eb; }}
.upload-header-btn:hover, .upload-header-btn.dragover {{ background-color: #dbeafe; border-color: #1d4ed8; color: #1d4ed8; box-shadow: 0 4px 12px rgba(37,99,235,0.15); transform: translateY(-1px); }}
.upload-header-btn.loading {{ opacity: 0.7; pointer-events: none; }}

.container {{ display:flex; height:calc(100vh - 60px); width: 100%; box-sizing:border-box; }}
.left-pane {{ width: 55%; min-width: 200px; background:#e2e8f0; position: relative; overflow: hidden; display: flex; flex-direction: row; }}

/* 侧边栏调整 */
.page-sidebar {{ width: 100px; background: #f1f5f9; display: flex; flex-direction: column; overflow-y: auto; flex-shrink: 0; border-right: 1px solid #cbd5e1; padding: 15px 10px; gap: 12px; align-items: center; box-shadow: inset -2px 0 5px rgba(0,0,0,0.02); }}
.page-sidebar::-webkit-scrollbar {{ width: 6px; }}
.page-sidebar::-webkit-scrollbar-thumb {{ background-color: #cbd5e1; border-radius: 3px; }}
.page-sidebar::-webkit-scrollbar-track {{ background-color: transparent; }}

/* 画布主区域包装器 */
.canvas-area {{ flex: 1; display: flex; flex-direction: column; position: relative; overflow: hidden; }}

/* 分页缩略图调整 */
.page-thumb {{ width: 75px; height: 95px; background: #fff; cursor: pointer; border: 1px solid #cbd5e1; border-radius: 6px; display: flex; flex-direction: column; align-items: center; justify-content: center; font-size: 12px; color: #64748b; transition: all 0.2s cubic-bezier(0.25, 0.8, 0.25, 1); flex-shrink: 0; box-shadow: 0 2px 4px rgba(0,0,0,0.04); position: relative; user-select: none; }}
.page-thumb:hover {{ transform: translateY(-3px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); border-color: #94a3b8; color: #334155; }}
.page-thumb.active {{ border: 2px solid #3b82f6; background: #fff; box-shadow: 0 0 0 3px rgba(59,130,246,0.15); color: #3b82f6; font-weight: bold; }}
.page-thumb-num {{ font-size: 16px; font-weight: 700; margin-bottom: 2px; }} 
.page-thumb-label {{ font-size: 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }} 
.page-thumb.active .page-thumb-label {{ color: #3b82f6; }}

.canvas-wrapper {{ flex: 1; overflow: auto; padding: 30px; position: relative; display: block; text-align: center; }}
.page-container {{ position: relative; transition: width 0.1s ease-out; background: white; box-shadow: 0 8px 30px rgba(0,0,0,0.12); display: inline-block; line-height: 0; margin: 0 auto; text-align: left; border-radius: 2px; }}
.page-container img {{ display: block; width: 100%; height: auto; }}

/* SVG 覆盖层与自定义悬浮提示框 */
.overlay-svg {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 10; pointer-events: none; }}
.overlay-svg polygon {{ fill: transparent; stroke-width: 2px; stroke-opacity: 0.6; fill-opacity: 0.1; cursor: pointer; pointer-events: auto; transition: all 0.15s; vector-effect: non-scaling-stroke; outline: none; }}
.overlay-svg polygon:hover {{ fill-opacity: 0.3; stroke-width: 3px; outline: none; }}
.overlay-svg polygon.active {{ fill: rgba(255, 0, 0, 0.2) !important; stroke: #ff0000 !important; stroke-width: 4px !important; stroke-opacity: 1 !important; animation: flash 1s infinite alternate; }}

/* 自定义的 SVG 悬浮信息框样式 (取消了 capitalize 大写限制) */
.custom-svg-tooltip {{ position: fixed; display: none; color: #ffffff; padding: 5px 12px; border-radius: 4px; font-size: 12px; font-weight: 600; pointer-events: none; z-index: 9999; box-shadow: 0 3px 10px rgba(0,0,0,0.2); text-transform: none; letter-spacing: 0.5px; transition: background-color 0.15s; }}

/* 悬浮工具栏样式优化（去除双层框） */
.svg-toolbar {{ position: absolute; display: none; z-index: 1000; }}
.svg-toolbar button {{ background: #fff; border: 1px solid #3b82f6; border-radius: 6px; cursor: pointer; padding: 6px 14px; margin: 0; color: #3b82f6; font-weight: 600; font-size: 12px; box-shadow: 0 4px 12px rgba(59,130,246,0.2); transition: all 0.2s ease; outline: none; }}
.svg-toolbar button:hover {{ background: #3b82f6; color: #fff; transform: translateY(-1px); box-shadow: 0 6px 16px rgba(59,130,246,0.3); }}

.resizer {{ width: 6px; background: #cbd5e1; cursor: col-resize; z-index: 100; flex-shrink: 0; border-left: 1px solid #94a3b8; border-right: 1px solid #94a3b8; transition: background 0.2s; }}
.resizer:hover, .resizer.resizing {{ background: #3b82f6; border-color: #3b82f6; }}

.right-pane {{ flex: 1; min-width: 300px; background:#fff; display: flex; flex-direction: column; overflow: hidden; }}
.tab-header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; background: #fcfcfc; padding: 0 15px; flex-shrink: 0; height: 45px; }}
.tab-group {{ display: flex; height: 100%; }}
.tab-btn {{ padding: 0 20px; height: 100%; cursor: pointer; border: none; background: transparent; font-weight: 600; color: #64748b; border-bottom: 3px solid transparent; font-size: 14px; display: flex; align-items: center; gap: 5px; transition: color 0.2s; }}
.tab-btn:hover {{ color: #3b82f6; background: #f8fafc; }}
.tab-btn.active {{ color: #3b82f6; border-bottom-color: #3b82f6; background: transparent; font-weight: 700; }}
.icon-btn {{ padding: 6px 10px; cursor: pointer; border: 1px solid transparent; background: transparent; color: #64748b; border-radius: 4px; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }}
.icon-btn:hover {{ background: #e2e8f0; color: #334155; }}
.download-controls {{ display: flex; align-items: center; gap: 8px; }}
.download-select {{ padding: 5px 8px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 12px; color: #334155; background: #fff; cursor: pointer; outline: none; }}
.download-select:hover, .download-select:focus {{ border-color: #3b82f6; }}
.view-container {{ flex: 1; overflow: hidden; position: relative; display: flex; flex-direction: column; }}
.markdown-view {{ padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 15px; height: 100%; box-sizing: border-box; background: #fff; }}
.json-view {{ padding: 0; overflow: hidden; display: none; height: 100%; box-sizing: border-box; background: #f8fafc; }}
.json-code {{ margin: 0; padding: 20px; font-family: "Consolas", "Monaco", "Courier New", monospace; font-size: 13px; line-height: 1.5; color: #24292e; white-space: pre-wrap; overflow: auto; height: 100%; }}

.json-code .string {{ color: #032f62; }}
.json-code .number {{ color: #005cc5; }}
.json-code .boolean {{ color: #d73a49; font-weight: 600; }}
.json-code .null {{ color: #6a737d; font-style: italic; }}
.json-code .key {{ color: #22863a; font-weight: 600; }}

.draggable {{ border: 1px solid #e2e8f0; border-left: 4px solid #cbd5e1; padding: 15px; background: #fff; transition: all 0.2s; border-radius: 6px; position: relative; margin-bottom: 5px; }}
.draggable:hover {{ box-shadow: 0 4px 10px rgba(0,0,0,0.06); border-color: #cbd5e1; }}
.draggable.active {{ border-color: #ef4444 !important; background: #fef2f2 !important; box-shadow: 0 0 0 2px rgba(239,68,68,0.2); }}
.controls {{ display:flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 12px; color: #64748b; border-bottom: 1px dashed #e2e8f0; padding-bottom: 5px; }}
.controls .info-tag-group {{ display: flex; align-items: center; gap: 8px; }}
.controls .info-order-index {{ font-weight: bold; font-size: 12px; color: #94a3b8; font-family: monospace; }}
.controls .info-order-tag {{ padding: 3px 8px; border-radius: 4px; color: white; font-weight: 600; font-size: 11px; white-space: nowrap; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }}
.controls .info-block-id {{ flex: 1; text-align: center; color: #94a3b8; font-size: 12px; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 10px; }}
.btn-group {{ display: flex; gap: 6px; align-items: center; }}
.btn-group button {{ border: 1px solid #e2e8f0; background: #f8fafc; cursor: pointer; padding: 3px 8px; border-radius: 4px; font-size: 12px; color: #64748b; transition: all 0.1s; white-space: nowrap; }}
.btn-group button:hover {{ background: #e2e8f0; color: #334155; border-color: #cbd5e1; }}
.editable {{ padding: 10px; background: #f8fafc; border: 1px solid transparent; color: #334155; font-family: "Consolas", monospace; font-size: 13px; min-height: 20px; margin-bottom: 10px; outline: none; white-space: pre-wrap; border-radius: 4px; line-height: 1.6; }}
.editable:focus {{ background: #fff; border-color: #3b82f6; color: #000; box-shadow: 0 0 0 2px rgba(59,130,246,0.1); }}
.rendered-box {{ padding: 10px; border-top: 1px solid #f1f5f9; margin-top: 5px; font-size: 15px; line-height: 1.6; color: #1e293b; }}
.rendered-box img {{ max-width: 100%; border-radius: 4px; border: 1px solid #e2e8f0; }}
.rendered-box[data-type="latex"] {{ font-size: 16px; padding: 15px; background: #fff; border: 1px solid #e2e8f0; text-align: center; overflow-x: auto; border-radius: 4px; }}
.rendered-box[data-type="html"] {{ overflow-x: auto; padding: 15px; background: #fff; border-radius: 4px; }}
.rendered-box[data-type="html"] table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 0; }}
.rendered-box[data-type="html"] th, .rendered-box[data-type="html"] td {{ border: 1px solid #cbd5e1; padding: 8px 10px; text-align: left; min-width: 20px; }}
.rendered-box[data-type="html"] th {{ background: #f1f5f9; font-weight: 600; }}
.rendered-box[data-type="html"] tr:nth-child(even) {{ background-color: #f8fafc; }}
.zoom-controls {{ position: absolute; top: 20px; left: 50%; transform: translateX(-50%); background: rgba(30,41,59,0.8); padding: 6px 10px; border-radius: 30px; display: flex; gap: 8px; z-index: 100; box-shadow: 0 4px 15px rgba(0,0,0,0.2); backdrop-filter: blur(4px); }}
.zoom-btn {{ background: transparent; border: none; color: rgba(255,255,255,0.9); font-weight: bold; width: 24px; height: 24px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 16px; border-radius: 50%; transition: background 0.2s; }}
.zoom-btn:hover {{ background: rgba(255,255,255,0.2); color: #fff; }}
@keyframes flash {{ 0% {{ opacity: 0.5; }} 100% {{ opacity: 1; }} }}
</style>

<script>
window.MathJax = {{
  tex: {{ packages: {{'[+]': ['upgreek', 'boldsymbol']}}, inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$','$$'], ['\\\\[','\\\\]']] }},
  loader: {{ load: ['[tex]/upgreek', '[tex]/boldsymbol'] }},
  options: {{ skipHtmlTags: ['script','noscript','style','textarea','pre','code'], ignoreHtmlClass: 'editable' }},
  startup: {{ ready() {{ MathJax.startup.defaultReady(); MathJax.startup.promise = MathJax.startup.promise.catch(() => {{}}); }} }}
}};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<script>
var RAW_JSON_DATA = {raw_json_js};
var CURRENT_ANNO_ID = null;
var BASE_WIDTH = 0;
var currentScale = 1.0;
var pageContainer = null;
var canvasWrapper = null;

// 生成高亮 JSON 字符串的函数
window.syntaxHighlightJSON = function(jsonObj) {{
    let json = JSON.stringify(jsonObj, null, 2);
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return json.replace(/("(\\u[a-zA-Z0-9]{{4}}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {{
        let cls = 'number';
        if (/^"/.test(match)) {{
            if (/:$/.test(match)) {{
                cls = 'key';
            }} else {{
                cls = 'string';
            }}
        }} else if (/true|false/.test(match)) {{
            cls = 'boolean';
        }} else if (/null/.test(match)) {{
            cls = 'null';
        }}
        return '<span class="' + cls + '">' + match + '</span>';
    }});
}};

function generateMarkdownFromJSON(data, withImg) {{
    return data.map(item => {{
        let content = "";
        let cat = (item.type || "").toLowerCase();
        
        if (item.latex_repr) content = "$$" + item.latex_repr + "$$";
        else if (cat === 'equation' && item.latex) content = "$$" + item.latex + "$$";
        else if (item.html) content = item.html;
        else if (item.structure) content = item.structure;
        else if (item.text || item.plain) {{
            let prefix = "";
            if (cat.includes('title') || cat.includes('header')) prefix = "# ";
            content = prefix + (item.text || item.plain);
        }}
        
        if (withImg) {{
            const annoId = item.anno_id;
            const imgEl = document.querySelector(`.draggable[data-anno-id='${{annoId}}'] .rendered-box img`);
            if (imgEl && imgEl.src) {{
                content += `\\n\\n![${{cat || 'image'}}](${{imgEl.src}})`;
            }}
        }}
        return content;
    }}).join("\\n\\n");
}}

// 【真实的文件流上传逻辑，支持轮询机制】
window.submitToBackend = async function(file) {{
    if(!file) return;
    
    const uploadBtn = document.querySelector('.upload-header-btn');
    const spanText = uploadBtn.querySelector('span');
    const originalText = spanText.innerText;
    
    uploadBtn.classList.add('loading');
    spanText.innerText = '正在上传解析...';

    // 构造 FormData
    const formData = new FormData();
    formData.append('file', file);

    try {{
        // 调用新增的 core_vis_upload_async 路由接口
        const response = await fetch('/api/vis/upload', {{
            method: 'POST',
            body: formData
        }});

        const resData = await response.json();
        
        if (response.ok && resData.token) {{
            spanText.innerText = '解析中...请稍候';
            
            // 开始智能轮询后端的 /view_together 接口
            const checkStatus = async () => {{
                try {{
                    const statusRes = await fetch(`/view_together?token=${{resData.token}}&pages=0`, {{
                        headers: {{ 'Accept': 'application/json, text/html' }}
                    }});
                    
                    const contentType = statusRes.headers.get("content-type");
                    
                    if (contentType && contentType.includes("application/json")) {{
                        const statusData = await statusRes.json();
                        if (statusData.status === "Error") {{
                            alert("解析失败：" + (statusData.description || "后端发生错误"));
                            uploadBtn.classList.remove('loading');
                            spanText.innerText = originalText;
                            return;
                        }}
                        setTimeout(checkStatus, 3000);
                    }} else {{
                        window.location.href = `/view_together?token=${{resData.token}}&pages=0`;
                    }}
                }} catch(err) {{
                    console.error("Polling error:", err);
                    setTimeout(checkStatus, 3000);
                }}
            }};
            // 延迟1秒后启动第一次轮询
            setTimeout(checkStatus, 1000);
            
        }} else {{
            alert("上传失败：" + (resData.description || resData.error || "接口异常"));
            uploadBtn.classList.remove('loading');
            spanText.innerText = originalText;
        }}
    }} catch (error) {{
        console.error("Upload error:", error);
        alert("网络请求异常: " + error.message);
        uploadBtn.classList.remove('loading');
        spanText.innerText = originalText;
    }}
}};

window.handleFileSelect = function(e) {{
    const files = e.target.files;
    if(files.length > 0) {{
        window.submitToBackend(files[0]);
    }}
    e.target.value = ''; 
}};

window.handleFileDrop = function(e) {{
    const files = e.dataTransfer.files;
    if(files.length > 0) {{
        window.submitToBackend(files[0]);
    }}
}};

window.goToPage = function(pageIdx) {{
    const url = new URL(window.location.href);
    url.searchParams.set('pages', pageIdx);
    window.location.href = url.toString();
}};

window.refreshOrderIds = function() {{
    const items = document.querySelectorAll('.draggable');
    items.forEach((item, index) => {{
        const indexSpan = item.querySelector('.info-order-index');
        if (indexSpan) {{ indexSpan.innerText = "No." + index; }}
        const annoId = item.getAttribute('data-anno-id');
        const dataItem = RAW_JSON_DATA.find(x => String(x.anno_id) === String(annoId));
        if (dataItem) {{ dataItem.order = index; }}
    }});
}};

window.moveItem = function(btn, direction) {{
    const current = btn.closest('.draggable');
    const annoId = current.getAttribute('data-anno-id');
    const parent = current.parentNode;
    const idx = RAW_JSON_DATA.findIndex(item => String(item.anno_id) === String(annoId));
    if (idx === -1) return;
    let targetIdx = -1;
    if (direction === 'up') {{
        const prev = current.previousElementSibling;
        if (prev) {{ parent.insertBefore(current, prev); if (idx > 0) targetIdx = idx - 1; }}
    }} else if (direction === 'down') {{
        const next = current.nextElementSibling;
        if (next) {{ parent.insertBefore(next, current); if (idx < RAW_JSON_DATA.length - 1) targetIdx = idx + 1; }}
    }}
    if (targetIdx !== -1) {{
        const temp = RAW_JSON_DATA[idx]; RAW_JSON_DATA[idx] = RAW_JSON_DATA[targetIdx]; RAW_JSON_DATA[targetIdx] = temp;
        for (let i = 0; i < RAW_JSON_DATA.length; i++) {{ if (RAW_JSON_DATA[i]) RAW_JSON_DATA[i].order = i; }}
    }}
    current.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
    window.refreshOrderIds();
    if(document.getElementById('view-json').style.display !== 'none') {{
         document.querySelector('.json-code').innerHTML = window.syntaxHighlightJSON(RAW_JSON_DATA);
    }}
}};

window.copyContent = async function(btn, type) {{
    const container = btn.closest('.draggable');
    try {{
        if (type === 'image') {{
            const img = container.querySelector('img');
            if(img) {{
                const resp = await fetch(img.src); const blob = await resp.blob();
                await navigator.clipboard.write([new ClipboardItem({{[blob.type]: blob}})]);
                btn.innerText = "已复制";
            }} else {{
                const annoId = container.getAttribute('data-anno-id');
                const success = await cropAndCopyFromCanvas(annoId);
                if(success) btn.innerText = "已截图";
                else btn.innerText = "无图";
            }}
        }} else {{
            const textEl = container.querySelector('.editable');
            if(textEl) {{ await navigator.clipboard.writeText(textEl.innerText); btn.innerText = "已复制"; }}
        }}
        setTimeout(() => btn.innerText = "复制", 1500);
    }} catch (err) {{ console.error('Copy failed:', err); btn.innerText = "失败"; }}
}};

window.cropAndCopyFromCanvas = function(annoId) {{
    return new Promise((resolve) => {{
        const item = RAW_JSON_DATA.find(x => String(x.anno_id) === String(annoId));
        if (!item || !item.bbox) {{ resolve(false); return; }}
        const mainImg = document.getElementById('main-page-image');
        if (!mainImg) {{ resolve(false); return; }}
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const w = mainImg.naturalWidth;
        const h = mainImg.naturalHeight;
        
        let minX, minY, cropW, cropH;
        if (item.bbox.x1 !== undefined) {{
             minX = Math.max(0, Math.floor(item.bbox.x1));
             minY = Math.max(0, Math.floor(item.bbox.y1));
             cropW = Math.ceil(item.bbox.x2 - item.bbox.x1);
             cropH = Math.ceil(item.bbox.y2 - item.bbox.y1);
        }} else if (item.poly) {{
             const poly = item.poly;
             const xs = poly.filter((_, i) => i % 2 === 0);
             const ys = poly.filter((_, i) => i % 2 !== 0);
             minX = Math.max(0, Math.floor(Math.min(...xs)));
             minY = Math.max(0, Math.floor(Math.min(...ys)));
             const maxX = Math.min(w, Math.ceil(Math.max(...xs)));
             const maxY = Math.min(h, Math.ceil(Math.max(...ys)));
             cropW = maxX - minX;
             cropH = maxY - minY;
        }}

        if (cropW <= 0 || cropH <= 0) {{ resolve(false); return; }}
        canvas.width = cropW;
        canvas.height = cropH;
        ctx.drawImage(mainImg, minX, minY, cropW, cropH, 0, 0, cropW, cropH);
        canvas.toBlob(blob => {{
            if (!blob) {{ resolve(false); return; }}
            navigator.clipboard.write([new ClipboardItem({{[blob.type]: blob}})])
                .then(() => resolve(true))
                .catch(err => {{ console.error('Clipboard write failed', err); resolve(false); }});
        }}, 'image/png');
    }});
}};

window.handleSvgScreenshot = async function() {{
    if (!CURRENT_ANNO_ID) return;
    const btn = document.getElementById('btn-svg-img');
    const originalText = btn.innerText;
    btn.innerText = "复制中...";
    const success = await cropAndCopyFromCanvas(CURRENT_ANNO_ID);
    if (success) {{ btn.innerText = "已复制"; }} else {{ btn.innerText = "失败"; }}
    setTimeout(() => btn.innerText = originalText, 1500);
}};

window.showSvgToolbar = function(annoId) {{
    CURRENT_ANNO_ID = annoId;
    const poly = document.querySelector(`.overlay-svg polygon[data-anno-id='${{annoId}}']`);
    const toolbar = document.getElementById('svg-toolbar');
    const wrapper = canvasWrapper || document.querySelector('.canvas-wrapper');
    const btn = document.getElementById('btn-svg-img');
    if (btn) btn.innerText = "复制截图";
    if (poly && toolbar && wrapper) {{
        const polyRect = poly.getBoundingClientRect();
        const wrapperRect = wrapper.getBoundingClientRect();
        let top = (polyRect.top - wrapperRect.top) + wrapper.scrollTop - 35;
        let left = (polyRect.right - wrapperRect.left) + wrapper.scrollLeft;
        
        if (top < wrapper.scrollTop) top = wrapper.scrollTop + 5;
        if (left > wrapper.scrollWidth - 80) left = wrapper.scrollWidth - 80;
        
        toolbar.style.top = top + 'px';
        toolbar.style.left = left + 'px';
        toolbar.style.display = 'block';
    }}
}};

window.hideSvgToolbar = function() {{
    const toolbar = document.getElementById('svg-toolbar');
    if (toolbar) toolbar.style.display = 'none';
    CURRENT_ANNO_ID = null;
}};

function clearHighlight() {{
    document.querySelectorAll('.overlay-svg polygon').forEach(p => p.classList.remove('active')); 
    document.querySelectorAll('.draggable').forEach(b => b.classList.remove('active')); 
}}

window.highlightFromLeft = function(evt, ele) {{
    evt.stopPropagation(); 
    switchTab('markdown');
    const annoId = ele.getAttribute('data-anno-id');
    clearHighlight(); 
    if (ele) ele.classList.add('active');
    const block = document.querySelector(`.draggable[data-anno-id='${{annoId}}']`);
    if (block) {{ block.classList.add('active'); block.scrollIntoView({{ behavior: "smooth", block: "center" }}); }}
    showSvgToolbar(annoId);
}};

window.highlightFromRight = function(annoId) {{
    clearHighlight();
    const block = document.querySelector(`.draggable[data-anno-id='${{annoId}}']`);
    const poly = document.querySelector(`.overlay-svg polygon[data-anno-id='${{annoId}}']`);
    const wrapper = canvasWrapper || document.querySelector('.canvas-wrapper');
    if (block) block.classList.add('active');
    if (poly && wrapper) {{
        poly.classList.add('active');
        const polyRect = poly.getBoundingClientRect();
        const wrapperRect = wrapper.getBoundingClientRect();
        const targetLeft = wrapper.scrollLeft + (polyRect.left - wrapperRect.left) - (wrapperRect.width / 2) + (polyRect.width / 2);
        const targetTop = wrapper.scrollTop + (polyRect.top - wrapperRect.top) - (wrapperRect.height / 2) + (polyRect.height / 2);
        wrapper.scrollTo({{ left: targetLeft, top: targetTop, behavior: 'smooth' }});
        showSvgToolbar(annoId);
    }}
}};

window.zoom = function(delta) {{ 
    currentScale = Math.max(0.1, currentScale + delta); 
    const container = pageContainer || document.querySelector('.page-container');
    if (BASE_WIDTH > 0 && container) {{
        container.style.width = (BASE_WIDTH * currentScale) + 'px';
    }}
    hideSvgToolbar(); 
}}

window.zoomFit = function() {{ 
    const container = pageContainer || document.querySelector('.page-container');
    const wrapper = canvasWrapper || document.querySelector('.canvas-wrapper');
    if(wrapper && container) {{
        const img = document.getElementById('main-page-image');
        if (img && img.naturalWidth) BASE_WIDTH = img.naturalWidth;
        const w = BASE_WIDTH || 1000;
        const wrapperW = wrapper.clientWidth; 
        if (w > 0) currentScale = (wrapperW - 60) / w; 
        container.style.width = (w * currentScale) + 'px';
        hideSvgToolbar();
    }} 
}}

window.switchTab = function(mode) {{
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`.tab-btn[data-mode="${{mode}}"]`).classList.add('active');
    
    document.getElementById('view-markdown').style.display = mode === 'markdown' ? 'flex' : 'none';
    document.getElementById('view-json').style.display = mode === 'json' ? 'block' : 'none';
    
    const mdExportSelect = document.getElementById('md-export-mode');
    if (mdExportSelect) {{
        mdExportSelect.style.display = mode === 'markdown' ? 'inline-block' : 'none';
    }}

    window.currentMode = mode;
    if(mode === 'markdown' && window.MathJax) MathJax.typesetPromise().catch(()=>{{}});
    if (mode === 'json') {{ document.querySelector('.json-code').innerHTML = window.syntaxHighlightJSON(RAW_JSON_DATA); }}
}};

window.downloadCurrentFile = function() {{
    const modeSelect = document.getElementById('md-export-mode');
    const withImg = (modeSelect && modeSelect.value === 'image');
    let content = "", filename = "{base_name}";
    if (window.currentMode === 'markdown') {{ 
        content = generateMarkdownFromJSON(RAW_JSON_DATA, withImg); 
        filename += withImg ? "_with_images.md" : ".md"; 
    }} 
    else {{ 
        content = JSON.stringify(RAW_JSON_DATA, null, 2); 
        filename += ".json"; 
    }}
    const blob = new Blob([content], {{ type: 'text/plain;charset=utf-8' }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
}};

document.addEventListener("DOMContentLoaded", function() {{
    pageContainer = document.querySelector('.page-container');
    canvasWrapper = document.querySelector('.canvas-wrapper');
    const markdownView = document.getElementById('view-markdown');
    
    const svgTooltip = document.createElement('div');
    svgTooltip.className = 'custom-svg-tooltip';
    document.body.appendChild(svgTooltip);

    document.addEventListener('mousemove', function(e) {{
        if (e.target && e.target.tagName && e.target.tagName.toLowerCase() === 'polygon') {{
            const cat = e.target.getAttribute('data-cat');
            const color = e.target.getAttribute('stroke');
            if(cat) {{
                svgTooltip.innerText = cat;
                svgTooltip.style.backgroundColor = color;
                svgTooltip.style.display = 'block';
                svgTooltip.style.left = (e.clientX + 15) + 'px';
                svgTooltip.style.top = (e.clientY + 15) + 'px';
            }}
        }} else {{
            svgTooltip.style.display = 'none';
        }}
    }});
    
    switchTab('markdown');

    if (markdownView) {{
        markdownView.addEventListener('click', function(e) {{
            const block = e.target.closest('.draggable');
            if (block && !e.target.closest('button') && !e.target.classList.contains('editable')) {{
                const annoId = block.getAttribute('data-anno-id');
                if (annoId) window.highlightFromRight(annoId);
            }}
        }});
    }}

    canvasWrapper.addEventListener('click', function(e) {{
        if (!e.target.closest('polygon') && !e.target.closest('.svg-toolbar')) {{
            clearHighlight();
            hideSvgToolbar();
        }}
    }});

    document.body.addEventListener('input', function(e) {{
        if (e.target.classList.contains('editable')) {{
            const parent = e.target.closest('.draggable');
            const annoId = parent.getAttribute('data-anno-id');
            const renderBox = parent.querySelector('.rendered-box');
            const newText = e.target.innerText;
            const item = RAW_JSON_DATA.find(x => String(x.anno_id) === String(annoId));
            if (item) {{
                if (item.latex_repr !== undefined) item.latex_repr = newText;
                else if (item.latex !== undefined) item.latex = newText;
                else if (item.html !== undefined) item.html = newText; 
                else if (item.structure !== undefined) item.structure = newText;
                else if (item.text !== undefined) item.text = newText;
                else if (item.plain !== undefined) item.plain = newText;
            }}
            if (renderBox) {{
                const type = renderBox.getAttribute('data-type');
                if (type === 'latex') {{ renderBox.textContent = "$$" + newText + "$$"; }} 
                else if (type === 'html') {{ renderBox.innerHTML = newText; }} 
                else {{ renderBox.innerText = newText; }}
                if(window.MathJax) {{ MathJax.typesetPromise([renderBox]).catch(err => console.log(err)); }}
            }}
            if(document.getElementById('view-json').style.display !== 'none') {{
                document.querySelector('.json-code').innerHTML = window.syntaxHighlightJSON(RAW_JSON_DATA);
            }}
        }}
    }});

    window.onload = function() {{ 
        const img = document.getElementById('main-page-image');
        if (img && img.complete) {{
             BASE_WIDTH = img.naturalWidth;
             window.zoomFit();
        }} else if (img) {{
             img.onload = function() {{
                 BASE_WIDTH = img.naturalWidth;
                 window.zoomFit();
             }}
        }} else {{
             setTimeout(window.zoomFit, 100); 
        }}
    }};

    const resizer = document.getElementById('dragMe'); const leftPane = document.querySelector('.left-pane'); const container = document.querySelector('.container'); let isResizing = false;
    resizer.addEventListener('mousedown', function(e) {{ isResizing = true; resizer.classList.add('resizing'); }});
    document.addEventListener('mousemove', function(e) {{ if (!isResizing) return; const containerRect = container.getBoundingClientRect(); let newWidthPercent = ((e.clientX - containerRect.left) / containerRect.width) * 100; leftPane.style.width = Math.max(20, Math.min(80, newWidthPercent)) + '%'; hideSvgToolbar(); }});
    document.addEventListener('mouseup', function(e) {{ if (isResizing) {{ isResizing = false; resizer.classList.remove('resizing'); window.zoomFit(); }} }});
    if(window.MathJax) MathJax.typesetPromise();
}});
</script>
</head>
<body>
<div class="info_header">
    <div class="header-left">
        <div class="header-logo">UniParser <span>Viz</span></div>
        <div class="doc-info">
            <span class="doc-icon">📄</span>
            <span class="doc-name">{base_name}</span>
            <span class="page-badge">Page {current_page_num} / {total_pages}</span>
        </div>
    </div>
    <!-- <div class="header-right">
        <div class="upload-header-btn" onclick="document.getElementById('file-upload-input').click()" 
             ondragover="event.preventDefault(); this.classList.add('dragover');" 
             ondragleave="this.classList.remove('dragover');" 
             ondrop="event.preventDefault(); this.classList.remove('dragover'); handleFileDrop(event);">
            <input type="file" id="file-upload-input" style="display:none;" onchange="handleFileSelect(event)" accept="*/*">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            <span>点击或拖入文件上传</span>
        </div>
    </div> -->
</div>
<div class="container">
    <div class="left-pane">
        {page_sidebar_block}
        <div class="canvas-area">
            <div class="zoom-controls">
                <button class="zoom-btn" onclick="zoom(-0.1)">-</button>
                <button class="zoom-btn" onclick="zoomFit()">[]</button>
                <button class="zoom-btn" onclick="zoom(0.1)">+</button>
            </div>
            <div class="canvas-wrapper">
                {content_image_block}
                <div id="svg-toolbar" class="svg-toolbar">
                    <button id="btn-svg-img" onclick="handleSvgScreenshot()">复制截图</button>
                </div>
            </div>
        </div>
    </div>
    <div class="resizer" id="dragMe"></div>
    <div class="right-pane">
        <div class="tab-header">
            <div class="tab-group"><button class="tab-btn active" onclick="switchTab('markdown')" data-mode="markdown">Markdown</button><button class="tab-btn" onclick="switchTab('json')" data-mode="json">JSON</button></div>
            <div class="download-controls">
                <select id="md-export-mode" class="download-select" title="选择Markdown导出模式">
                    <option value="text">MD (纯文本)</option>
                    <option value="image">MD (含图片)</option>
                </select>
                <button class="icon-btn" onclick="downloadCurrentFile()" title="下载文件">💾</button>
            </div>
        </div>
        <div class="view-container">
            <div id="view-markdown" class="markdown-view">{content_list}</div>
            <div id="view-json" class="json-view"><pre class="json-code"></pre></div>
        </div>
    </div>
</div>
</body>
</html>
"""


class UniparserJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if is_dataclass(obj):
            return asdict(obj)
        if hasattr(obj, "__dict__"):
            d = obj.__dict__.copy()
            for k in list(d.keys()):
                if k.startswith("_"):
                    d.pop(k)
            return d
        if hasattr(obj, "value"):
            return obj.value
        return super().default(obj)


def crop_image_to_base64(pil_image: Image.Image, poly: Union[List[float], BBox]) -> str:
    try:
        if not pil_image:
            return ""

        if hasattr(poly, "x1"):
            left, top, right, bottom = poly.x1, poly.y1, poly.x2, poly.y2
        elif isinstance(poly, list) and len(poly) >= 4:
            xs, ys = poly[0::2], poly[1::2]
            left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        else:
            return ""

        w, h = pil_image.size
        left, top = max(0, min(left, w - 1)), max(0, min(top, h - 1))
        right, bottom = max(left + 1, min(right, w)), max(top + 1, min(bottom, h))
        if right <= left or bottom <= top:
            return ""

        cropped = pil_image.crop((int(left), int(top), int(right), int(bottom)))
        return dump_image_base64_str(cropped)
    except Exception:
        return ""


def generate_svg_overlay(layout_items: List[SemanticItem], width: int, height: int) -> str:
    svg_parts = [f'<svg class="overlay-svg" viewBox="0 0 {width} {height}" preserveAspectRatio="none">']
    for idx, item in enumerate(layout_items):
        bbox = item.bbox
        if not bbox:
            continue

        anno_id = str(idx)
        cat = get_mapped_category(item)
        color = LABEL_COLORS.get(cat, "#ff0000")
        points = [(bbox.x1, bbox.y1), (bbox.x2, bbox.y1), (bbox.x2, bbox.y2), (bbox.x1, bbox.y2)]

        try:
            points_str = " ".join([f"{p[0]},{p[1]}" for p in points])
            svg_parts.append(
                f'<polygon points="{points_str}" data-anno-id="{anno_id}" data-cat="{html.escape(str(cat))}" '
                f'stroke="{color}" onclick="highlightFromLeft(event, this)">'
                f"</polygon>"
            )
        except Exception:
            continue
    svg_parts.append("</svg>")
    return "".join(svg_parts)


def populate_table_html(item: TabularResult) -> str:
    html_val = getattr(item, "html", "")
    if html_val:
        return html_val

    structure = getattr(item, "structure", "")
    if not structure:
        return ""

    contents = getattr(item, "contents", [])

    if contents and isinstance(contents, list) and "rec-" in structure:

        def replace_match(match):
            try:
                idx = int(match.group(1))
                if 0 <= idx < len(contents):
                    val = contents[idx]
                    return html.escape(str(val)) if val is not None else ""
            except (ValueError, IndexError):
                pass
            return ""

        return re.sub(r"rec-(\d+)", replace_match, structure)

    if contents and isinstance(contents, list):
        current_struct = structure
        for content in contents:
            txt = str(content) if content is not None else ""
            safe_txt = html.escape(txt)
            match = re.search(r"<((?:td|th))([^>]*)>\s*</\1>", current_struct, flags=re.IGNORECASE)
            if match:
                tag_name = match.group(1)
                attrs = match.group(2)
                replacement = f"<{tag_name}{attrs}>{safe_txt}</{tag_name}>"
                current_struct = current_struct.replace(match.group(0), replacement, 1)
            else:
                break
        return current_struct

    return structure


def render_det_to_html(item: SemanticItem, idx: int, pil_image: Image.Image) -> str:
    anno = str(idx)

    cat = get_mapped_category(item)
    cat_lower = cat.lower()
    color = LABEL_COLORS.get(cat, "#ccc")

    content_html = ""
    edit_val = ""
    copy_type = "text"

    text_content = ""
    if hasattr(item, "plain") and item.plain:
        text_content = item.plain
    elif hasattr(item, "text") and item.text:
        text_content = item.text

    is_group = isinstance(item, GroupedResult) or "group" in cat_lower
    is_text_annotation = any(x in cat_lower for x in ["caption", "footnote", "note"])
    is_header_footer_hline = cat_lower in ["header", "footer", "pageheader", "pagefooter", "hline", "watermark"]
    is_image_type = cat_lower in ["image", "figure"]

    if "equationid" in cat_lower or "moleculeid" in cat_lower:
        content_html = f'<div class="rendered-box" data-type="text">{html.escape(text_content)}</div>'
        edit_val = html.escape(text_content).strip()
        copy_type = "text"

    # 1. 公式 (Equation)
    elif (
        (getattr(item, "type", None) == LayoutType.Equation or "equation" in cat_lower)
        and "id" not in cat_lower
        and not is_text_annotation
    ):
        latex_content = getattr(item, "latex", text_content)
        if latex_content and str(latex_content).strip():
            edit_val = html.escape(str(latex_content)).strip()
            content_html = f'<div class="rendered-box" data-type="latex">$${edit_val}$$</div>'
        else:
            source_b64 = getattr(item, "source", "")
            if not source_b64:
                source_b64 = crop_image_to_base64(pil_image, getattr(item, "bbox", None))

            if source_b64:
                if not source_b64.startswith("data:"):
                    source_b64 = f"data:image/png;base64,{source_b64}"
                content_html = f'<div class="rendered-box" data-type="image"><img src="{source_b64}" /></div>'
                edit_val = "(区域截图)"
                copy_type = "image"
            else:
                content_html = '<div class="rendered-box" data-type="text">(Empty Formula)</div>'
                edit_val = ""

    # 2. 表格 (Table)
    elif (getattr(item, "type", None) == LayoutType.Table or "table" in cat_lower) and not is_text_annotation:
        full_html = getattr(item, "html", "")

        if full_html:
            edit_val = html.escape(full_html).strip()
            content_html = f'<div class="rendered-box" data-type="html">{full_html}</div>'
            copy_type = "html"
        else:
            edit_val = html.escape(text_content).strip()
            content_html = f'<div class="rendered-box" data-type="text">{edit_val}</div>'

    # 3. 图表 (Chart)
    elif (
        (getattr(item, "type", None) == LayoutType.Chart or "chart" in cat_lower)
        and not is_text_annotation
        and hasattr(item, "data")
        and item.data
    ):
        json_str = json.dumps(item.data, ensure_ascii=False, indent=2)
        content_html = f'<div class="rendered-box" data-type="json">{html.escape(json_str)}</div>'
        edit_val = "(Chart Data)"
        copy_type = "text"

    # 4. 分子式 (Molecule)
    elif (
        (getattr(item, "type", None) == LayoutType.Molecule or "molecule" in cat_lower)
        and "id" not in cat_lower
        and not is_text_annotation
        and (hasattr(item, "smi") and item.smi)
    ):
        if hasattr(item, "caption") and item.caption:
            content_html = f'<div class="rendered-box" data-type="text">{html.escape(str(item.caption))}</div>'
            edit_val = str(item.caption)
        elif hasattr(item, "smi") and item.smi:
            content_html = f'<div class="rendered-box" data-type="text">{html.escape(item.smi)}</div>'
            edit_val = item.smi

    # 5. Group, Header, Footer, Image, Figure, Chart(无数据), Molecule(无SMI)
    elif (
        is_group
        or is_header_footer_hline
        or is_image_type
        or (not is_text_annotation and ("chart" in cat_lower or "molecule" in cat_lower))
    ):
        source_b64 = getattr(item, "source", "")
        if not source_b64:
            source_b64 = crop_image_to_base64(pil_image, getattr(item, "bbox", None))

        if source_b64:
            if not source_b64.startswith("data:"):
                source_b64 = f"data:image/png;base64,{source_b64}"
            content_html = f'<div class="rendered-box" data-type="image"><img src="{source_b64}" /></div>'
            edit_val = "(区域截图)"
            copy_type = "image"
        else:
            if text_content:
                content_html = f'<div class="rendered-box" data-type="text">{html.escape(text_content)}</div>'
                edit_val = html.escape(text_content).strip()
            else:
                content_html = '<div class="rendered-box" data-type="text">(Empty Image)</div>'
                edit_val = ""

    elif text_content:
        content_html = f'<div class="rendered-box" data-type="text">{html.escape(text_content)}</div>'
        edit_val = html.escape(text_content).strip()

    else:
        source_b64 = crop_image_to_base64(pil_image, getattr(item, "bbox", None))
        if source_b64:
            if not source_b64.startswith("data:"):
                source_b64 = f"data:image/png;base64,{source_b64}"
            content_html = f'<div class="rendered-box" data-type="image"><img src="{source_b64}" /></div>'
            edit_val = "(区域截图)"
            copy_type = "image"
        else:
            content_html = '<div class="rendered-box" data-type="text">(Empty)</div>'
            edit_val = ""

    block_val = getattr(item, "block", "")

    return f"""
    <div class="draggable" data-anno-id="{anno}" style="border-left-color: {color}">
        <div class="controls">
            <div class="info-tag-group">
                <span class="info-order-index">No.{idx}</span>
                <span class="info-order-tag" data-cat="{cat}" style="background:{color}">{cat}</span>
            </div>
            <div class="info-block-id">block: {block_val}</div>
            <div class="btn-group">
                <button onclick="copyContent(this, '{copy_type}')">复制</button>
                <button onclick="moveItem(this, 'up')" title="上移">↑</button>
                <button onclick="moveItem(this, 'down')" title="下移">↓</button>
            </div>
        </div>
        <div class="editable" contenteditable="true" spellcheck="false">{edit_val}</div>
        {content_html}
    </div>
    """


def plotly_pdf_results_interactive(pages_data: List[Any], file_path: str, pages: Optional[List[int]] = None) -> Dict:
    total_pages = len(pages_data)
    if not pages:
        pages = [0]
    target_page_idx = pages[0]
    if target_page_idx >= total_pages:
        target_page_idx = 0

    pil_image = None
    pdf_w, pdf_h = 0, 0

    try:
        if str(file_path).lower().endswith(".pdf"):
            doc = fitz.open(file_path)
            if target_page_idx < len(doc):
                page = doc[target_page_idx]
                rect = page.rect
                pdf_w, pdf_h = rect.width, rect.height
                pix = page.get_pixmap(dpi=144)
                pil_image = Image.open(io.BytesIO(pix.tobytes("png")))
        else:
            pil_image = Image.open(file_path)
            pdf_w, pdf_h = pil_image.size
    except Exception as e:
        print(f"[Viz Error] Load image failed: {e}")
        pil_image = Image.new("RGB", (800, 1000), "white")
        pdf_w, pdf_h = 800, 1000

    img_w, img_h = pil_image.size
    current_page_blocks_raw = pages_data[target_page_idx] if target_page_idx < len(pages_data) else []

    temp_items: List[SemanticItem] = []
    if isinstance(current_page_blocks_raw, list):
        for block in current_page_blocks_raw:
            item_obj = build_item(block)
            temp_items.extend(flatten_semantic_items_obj(item_obj))

    is_normalized = False
    for item in temp_items:
        if item.bbox and getattr(item.bbox, "x2", 0) > 0 and getattr(item.bbox, "x2", 0) < 2.0:
            is_normalized = True
            break

    scale_x = img_w if is_normalized else ((img_w / pdf_w) if pdf_w > 0 else 1.0)
    scale_y = img_h if is_normalized else ((img_h / pdf_h) if pdf_h > 0 else 1.0)

    layout_items_processed: List[SemanticItem] = []
    for item in temp_items:
        if item.bbox:
            try:
                item.bbox = item.bbox * (scale_x, scale_y)
            except Exception:
                item.bbox.x1 *= scale_x
                item.bbox.x2 *= scale_x
                item.bbox.y1 *= scale_y
                item.bbox.y2 *= scale_y
        layout_items_processed.append(item)

    layout_items_processed.sort(key=lambda x: getattr(x, "order", 0) if getattr(x, "order", -1) != -1 else 0)

    return {
        "layout_items": layout_items_processed,
        "pil_image": pil_image,
        "filename": str(file_path).split("/")[-1],
        "page_index": target_page_idx,
        "total_pages": total_pages,
    }


def create_interactive_html_from_data(vis_data: Dict) -> str:
    layout_items = vis_data["layout_items"]
    pil_image = vis_data["pil_image"]
    filename = vis_data["filename"]
    total_pages = vis_data.get("total_pages", 1)
    current_page = vis_data.get("page_index", 0)

    sidebar_parts = ['<div class="page-sidebar">']

    for i in range(total_pages):
        active_cls = "active" if i == current_page else ""
        sidebar_parts.append(
            f'<div class="page-thumb {active_cls}" onclick="goToPage({i})">'
            f'<div class="page-thumb-num">{i + 1}</div>'
            f'<div class="page-thumb-label">PAGE</div>'
            f"</div>"
        )
    sidebar_parts.append("</div>")

    img_b64 = dump_image_base64_str(pil_image)
    svg_overlay = generate_svg_overlay(layout_items, pil_image.width, pil_image.height)

    content_image_block = f"""
    <div class="page-container">
        <img id="main-page-image" src="data:image/jpeg;base64,{img_b64}" alt="page" />
        {svg_overlay}
    </div>
    """

    content_list = "\n".join([render_det_to_html(item, idx, pil_image) for idx, item in enumerate(layout_items)])

    items_dicts = []
    for idx, item in enumerate(layout_items):
        d = asdict(item) if is_dataclass(item) else item.__dict__.copy()
        d = {k: v for k, v in d.items() if not k.startswith("_")}

        cat = get_mapped_category(item)

        if cat == LayoutType.Table.value or "table" in cat.lower():
            html_val = getattr(item, "html", "")
            if html_val:
                d["html"] = html_val
            elif getattr(item, "structure", ""):
                d["html"] = populate_table_html(item)

        d["anno_id"] = str(idx)
        d["type"] = cat
        items_dicts.append(d)

    json_data_str = json.dumps(items_dicts, ensure_ascii=False, cls=UniparserJSONEncoder)

    return HTML_TMPL.format(
        title=f"UniParser Viz - {filename}",
        base_name=filename,
        current_page_num=current_page + 1,
        total_pages=total_pages,
        page_sidebar_block="".join(sidebar_parts),
        content_image_block=content_image_block,
        content_list=content_list,
        raw_md_js="''",
        raw_json_js=json_data_str,
    )


def plotly_pdf_results(pages_data, file_path, pages=None):
    data = plotly_pdf_results_interactive(pages_data, file_path, pages)
    return create_interactive_html_from_data(data)

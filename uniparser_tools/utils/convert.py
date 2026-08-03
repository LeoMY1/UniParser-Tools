from functools import lru_cache
from inspect import Parameter, signature
from typing import Dict, List

from uniparser_tools.common.constant import FormatFlag, LayoutType, ParseMode, to_semantic
from uniparser_tools.common.dataclass import (
    ChartResult,
    EquationResult,
    ExpressionResult,
    FigureResult,
    GroupedResult,
    LayoutItem,
    MoleculeResult,
    Reaction,
    ReactionComponent,
    SemanticItem,
    TabularResult,
    TextualResult,
)
from uniparser_tools.utils.format_utils import parse_inline_text, parse_table_full_html
from uniparser_tools.utils.log import get_root_logger


@lru_cache(maxsize=None)
def _init_param_names(cls):
    return {
        name
        for name, param in signature(cls).parameters.items()
        if param.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
    }


def _filter_init_kwargs(cls, block: Dict):
    valid_keys = _init_param_names(cls)
    return {key: value for key, value in block.items() if key in valid_keys}


def _normalize_reaction_payload(reaction):
    if not isinstance(reaction, dict):
        return reaction

    normalized = _filter_init_kwargs(Reaction, reaction)
    for field_name in ("reactants", "conditions", "products"):
        components = normalized.get(field_name)
        if isinstance(components, list):
            normalized[field_name] = [
                _filter_init_kwargs(ReactionComponent, component) if isinstance(component, dict) else component
                for component in components
            ]
    return normalized


def _upgrade_table_structure_spans(block: Dict) -> None:
    if "html" in block:
        block["structure"] = block.pop("html")
    if "text" in block:
        block.pop("text")

    if block.get("placeholders"):
        if block.get("contents") and not block.get("types"):
            block["types"] = [LayoutType.Text] * len(block["contents"])
        return
    if block.get("structure"):
        block.update(parse_table_full_html(str(block["structure"])))


def build_item(block: Dict):
    if "pages" in block:
        block.pop("pages")
    if "reactions" in block:
        kwargs = _filter_init_kwargs(ExpressionResult, block)
        if isinstance(kwargs.get("reactions"), list):
            kwargs["reactions"] = [_normalize_reaction_payload(reaction) for reaction in kwargs["reactions"]]
        item = ExpressionResult(**kwargs)
    elif "placeholders" in block:
        _upgrade_table_structure_spans(block)
        item = TabularResult(**_filter_init_kwargs(TabularResult, block))
    elif "markush" in block:
        item = MoleculeResult(**_filter_init_kwargs(MoleculeResult, block))
    elif "data" in block:
        item = ChartResult(**_filter_init_kwargs(ChartResult, block))
    elif "desc" in block:
        item = FigureResult(**_filter_init_kwargs(FigureResult, block))
    elif "latex_repr" in block:
        item = EquationResult(**_filter_init_kwargs(EquationResult, block))
    elif "text" in block:
        kwargs = _filter_init_kwargs(TextualResult, block)
        if not kwargs.get("contents"):
            kwargs["contents"], kwargs["types"] = parse_inline_text(kwargs["text"])
            kwargs["bboxes"] = []
        if not kwargs.get("types", []):
            kwargs["types"] = [LayoutType.Text] * len(kwargs["contents"])
        kwargs["text"] = "".join(kwargs["contents"])
        item = TextualResult(**kwargs)
    elif "items" in block:
        kwargs = _filter_init_kwargs(GroupedResult, block)
        kwargs["items"] = [build_item(child) for child in block["items"]]
        item = GroupedResult(**kwargs)
    else:
        item = LayoutItem(**_filter_init_kwargs(LayoutItem, block))
    return item


def dict2obj(pages_dict: List[List[Dict]]):
    objs: List[List[SemanticItem]] = []
    for page in pages_dict:
        items: List[SemanticItem] = []
        for i in range(len(page)):
            block = page[i]
            item = build_item(block)
            items.append(item)
        objs.append(items)
    return objs


def item2format(item: SemanticItem, data: Dict, status: Dict):
    if item.type == LayoutType.Section:
        return ""

    if not data.__dict__.get("marginalia", True):
        if item.type in [
            LayoutType.PageHeader,
            LayoutType.PageFooter,
            LayoutType.PageBar,
            LayoutType.PageNote,
            LayoutType.PageNumber,
            LayoutType.Watermark,
        ]:
            return ""

    if isinstance(item, LayoutItem):
        s = ""
    else:
        if not isinstance(item, GroupedResult):
            try:
                item_format = data.__dict__[to_semantic(item.type)]
            except KeyError:
                if item.type in [
                    LayoutType.PageHeader,
                    LayoutType.PageFooter,
                ]:
                    item_format = data.__dict__[to_semantic(LayoutType.Paragraph)]
                else:
                    get_root_logger().exception(
                        f"Failed to get item format for {item.type} -> {to_semantic(item.type)}"
                    )
                    return ""
            # temporarily disabled for compatibility
            if False and item.type in [
                LayoutType.Molecule,
            ]:
                s = item.source
            else:
                s = getattr(item, item_format)
            if not item.plain and getattr(item, "source", ""):
                if status["dict_cfg"][to_semantic(item.type)] == ParseMode.DumpBase64:
                    # Use SVG for molecules, PNG for others
                    # temporarily disabled for compatibility
                    if False and item.type == LayoutType.Molecule:
                        mime_type = "image/svg+xml"
                    else:
                        mime_type = "image/png"
                    if item_format == FormatFlag.Markdown:
                        s += f"![{item.type}](data:{mime_type};base64,{item.source})"
                    elif item_format == FormatFlag.Html:
                        s += f"<img src='data:{mime_type};base64,{item.source}' alt='{item.type}'/>"
                elif status["dict_cfg"][to_semantic(item.type)] == ParseMode.DumpLocal:
                    if item_format == FormatFlag.Markdown:
                        s += f"![{item.type}]({item.source})"
                    elif item_format == FormatFlag.Html:
                        s += f"<img src='{item.source}' alt='{item.type}'/>"
                elif status["dict_cfg"][to_semantic(item.type)] == ParseMode.DumpHosting:
                    if item_format == FormatFlag.Markdown:
                        s += f"![{item.type}]({item.source})"
                    elif item_format == FormatFlag.Html:
                        s += f"<img src='{item.source}' alt='{item.type}'/>"
            if item_format == FormatFlag.Html:
                s += "<br>"
        else:
            s_ = []
            for item in item.items:
                s_.append(item2format(item, data, status))
            s = "\n\n".join(s_)
    return s

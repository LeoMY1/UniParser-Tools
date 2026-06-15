"""Shared helpers for UniParser skill CLI scripts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_HOST = "https://uniparser.dp.tech/"
INSTALL_CMD = "git+https://github.com/dptech-corp/UniParser-Tools.git"

# Hard-coded polling (not documented in SKILL.md as tunable).
POLL_INTERVAL_SEC = 3
POLL_TIMEOUT_SEC = 1800

PENDING_STATUSES = frozenset({"undefined", "waiting", "processing"})


def emit_json_stderr(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def config_error(message: str) -> int:
    emit_json_stderr({"ok": False, "error": {"code": "CONFIG_ERROR", "message": message}})
    return 1


def dir_exists_error(output_dir: Path) -> int:
    emit_json_stderr(
        {
            "ok": False,
            "error": {
                "code": "DIR_EXISTS",
                "message": (
                    f"Output directory already exists: {output_dir}. "
                    "Ask the user whether to continue parsing. "
                    "If they agree, re-run the same command with --overwrite."
                ),
                "output_dir": str(output_dir),
            },
        }
    )
    return 1


def parse_error(stage: str, result: dict) -> int:
    emit_json_stderr(
        {
            "ok": False,
            "error": {
                "code": "PARSE_ERROR",
                "message": result.get("description") or result.get("message") or str(result),
                "stage": stage,
            },
            "token": result.get("token"),
        }
    )
    return 1


def get_api_key() -> str | None:
    return (os.getenv("UNIPARSER_API_KEY") or "").strip() or None


def check_api_key() -> int | None:
    if get_api_key():
        return None
    return config_error(
        "UNIPARSER_API_KEY is not set. "
        "Register at https://uniparser.dp.tech/ then set the environment variable. "
        "See SKILL.md Configuration section for platform-specific commands."
    )


def _try_import_uniparser() -> bool:
    try:
        import uniparser_tools  # noqa: F401

        return True
    except ImportError:
        return False


def ensure_uniparser_installed() -> int | None:
    if _try_import_uniparser():
        return None
    subprocess.run(
        [sys.executable, "-m", "pip", "install", INSTALL_CMD],
        check=False,
    )
    if _try_import_uniparser():
        return None
    return config_error(f'uniparser_tools is not installed. Run once: pip install "{INSTALL_CMD}"')


def run_startup_checks() -> int | None:
    code = check_api_key()
    if code is not None:
        return code
    return ensure_uniparser_installed()


def source_stem_from_path(path: Path) -> str:
    return path.stem or "document"


def source_stem_from_url(url: str) -> str:
    """Last URL path segment; strip only known doc extensions (not arXiv ID dots)."""
    segment = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if not segment:
        return "url_document"
    lower = segment.lower()
    for ext in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
        if lower.endswith(ext):
            segment = segment[: -len(ext)]
            break
    return segment or "url_document"


def default_output_dir(source_stem: str) -> Path:
    return (Path.home() / "Uni-Parser-Skill" / source_stem).expanduser().resolve()


def resolve_fetch_target(
    *,
    token: str | None,
    file_path: str | None,
    image_path: str | None,
    pdf_url: str | None,
    client,
) -> tuple[str, str] | int:
    """Resolve task token and source_stem for fetch_by_token. Returns exit code on error."""
    provided = sum(1 for value in (token, file_path, image_path, pdf_url) if value is not None)
    if provided != 1:
        return config_error("Provide exactly one of --token, --file-path, --image-path, or --pdf-url.")

    if token is not None:
        resolved = token.strip()
        if not resolved:
            return config_error("Token must not be empty.")
        return resolved, f"token_{resolved[:8]}"

    if file_path is not None:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            return config_error(f"File not found: {path}")
        task_id = str(path)
        return client.to_token(task_id), source_stem_from_path(path)

    if image_path is not None:
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            return config_error(f"Image not found: {path}")
        task_id = str(path)
        return client.to_token(task_id), source_stem_from_path(path)

    task_id = pdf_url.strip()
    if not task_id:
        return config_error("PDF URL must not be empty.")
    return client.to_token(task_id), source_stem_from_url(task_id)


def resolve_output_dir(
    source_stem: str,
    output_dir: str | None,
    *,
    overwrite: bool,
) -> tuple[Path | None, int | None]:
    out = Path(output_dir).expanduser().resolve() if output_dir else default_output_dir(source_stem)
    if out.exists() and not overwrite:
        return None, dir_exists_error(out)
    if out.exists() and overwrite:
        shutil.rmtree(out)
    return out, None


def scientific_paper_trigger_kwargs(*, sync: bool = True) -> dict:
    from uniparser_tools.common.constant import ParseMode, ParseModeTextual

    return {
        "sync": sync,
        "textual": ParseModeTextual.OCRHighQuality,
        "equation": ParseMode.OCRHighQuality,
        "table": ParseMode.OCRHighQuality,
        "chart": ParseMode.DumpBase64,
        "figure": ParseMode.DumpBase64,
        "expression": ParseMode.DumpBase64,
        "molecule": ParseMode.OCRFast,
    }


def poll_until_success(client, token: str) -> dict | int:
    """Poll get_result until status is success. Returns result dict or exit code."""
    deadline = time.time() + POLL_TIMEOUT_SEC
    last: dict[str, Any] = {}

    while time.time() < deadline:
        last = client.get_result(
            token,
            content=False,
            objects=False,
            pages_dict=False,
            pages_tree=False,
        )
        status = last.get("status")
        if status == "success":
            return last
        if status == "error":
            return parse_error("get_result_poll", last)
        if status in PENDING_STATUSES or status is None:
            time.sleep(POLL_INTERVAL_SEC)
            continue
        return parse_error("get_result_poll", last)

    return parse_error(
        "get_result_poll",
        {
            "status": "error",
            "description": f"Timed out after {POLL_TIMEOUT_SEC}s waiting for parsing to finish.",
            "token": token,
            "last_status": last.get("status"),
        },
    )


def fetch_pages_tree(client, token: str) -> dict:
    return client.get_result(token, pages_tree=True, objects=False)


def fetch_markdown(client, token: str) -> dict:
    from uniparser_tools.common.constant import FormatFlag

    return client.get_formatted(
        token,
        content=True,
        textual=FormatFlag.Markdown,
        table=FormatFlag.Markdown,
        equation=FormatFlag.Latex,
    )


def save_parse_results(
    *,
    out_dir: Path,
    source_stem: str,
    pages_tree: dict,
    formatted: dict,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source_stem or "document"

    pages_tree_path = out_dir / "pages_tree.json"
    pages_tree_path.write_text(
        json.dumps(pages_tree, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    md_path = out_dir / f"{stem}.md"
    content = formatted.get("content", "")
    md_path.write_text(content, encoding="utf-8")

    meta = {k: v for k, v in formatted.items() if k != "content"}
    (out_dir / "formatted_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "output_dir": str(out_dir),
        "pages_tree_path": str(pages_tree_path),
        "markdown_path": str(md_path),
        "content_chars": len(content),
    }


def print_success(summary: dict) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Pages tree saved to: {summary['pages_tree_path']}", file=sys.stderr)
    print(f"Markdown saved to: {summary['markdown_path']}", file=sys.stderr)
    print(f"Output directory: {summary['output_dir']}", file=sys.stderr)

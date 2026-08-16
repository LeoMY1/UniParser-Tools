from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from uniparser_tools.cli.core.defaults import (
    DIRECT_SYNC_UPLOAD_REQUEST_TIMEOUT,
    DIRECT_UPLOAD_REQUEST_TIMEOUT,
    PENDING_STATUSES,
    POLL_INTERVAL_SEC,
    POLL_TIMEOUT_SEC,
    UNDEFINED_MAX_POLLS,
)
from uniparser_tools.cli.core.errors import parse_error, token_not_found_error, upload_error
from uniparser_tools.cli.core.input import InputKind, ResolvedInput, display_label_for_input
from uniparser_tools.cli.core.output import print_parsing_status, save_parse_results, write_trigger_meta
from uniparser_tools.cli.core.parse_options import resolve_trigger_kwargs, serialize_trigger_kwargs


def scientific_paper_trigger_kwargs(*, sync: bool = True) -> dict:
    return resolve_trigger_kwargs(sync=sync, overrides={})


def trigger_input(
    client,
    resolved: ResolvedInput,
    *,
    trigger_kwargs: dict,
    upload_mode: str = "auto",
) -> tuple[dict, str]:
    kwargs = trigger_kwargs
    if resolved.kind is InputKind.FILE:
        upload = None
        if upload_mode != "direct":
            upload = client.upload_files_to_tos([str(resolved.path)])
            if not isinstance(upload, dict):
                upload = {
                    "status": "error",
                    "message": "TOS upload returned an invalid response",
                }

            if upload.get("status") == "success":
                uploaded_files = upload.get("files")
                uploaded_file = uploaded_files[0] if isinstance(uploaded_files, list) and uploaded_files else None
                source_url = uploaded_file.get("source_url") if isinstance(uploaded_file, dict) else None
                if isinstance(source_url, str) and source_url:
                    trigger = client.trigger_url(
                        pdf_url=source_url,
                        server_generated_token=True,
                        **kwargs,
                    )
                    return trigger, "trigger_url"
                upload = {
                    "status": "error",
                    "message": "TOS upload response missing source_url",
                }

            if upload_mode == "tos":
                return upload, "upload_tos"

        trigger = client.trigger_file(
            file_path=str(resolved.path),
            server_generated_token=True,
            http_timeout=(
                DIRECT_SYNC_UPLOAD_REQUEST_TIMEOUT if kwargs.get("sync", True) else DIRECT_UPLOAD_REQUEST_TIMEOUT
            ),
            **kwargs,
        )
        if not isinstance(trigger, dict):
            trigger = {
                "status": "error",
                "message": "Direct upload returned an invalid response",
            }
        if trigger.get("status") != "success":
            if upload is not None:
                trigger["tos_upload_error"] = upload
        stage = "trigger_file_direct" if upload_mode == "direct" else "trigger_file_fallback"
        return trigger, stage
    if resolved.kind is InputKind.IMAGE:
        trigger = client.trigger_snip(
            snip_path=str(resolved.path),
            server_generated_token=True,
            **kwargs,
        )
        return trigger, "trigger_snip"
    trigger = client.trigger_url(
        pdf_url=resolved.raw,
        server_generated_token=True,
        **kwargs,
    )
    return trigger, "trigger_url"


def poll_until_success(client, token: str) -> dict | int:
    deadline = time.monotonic() + POLL_TIMEOUT_SEC
    last: dict[str, Any] = {}
    undefined_polls = 0

    while time.monotonic() < deadline:
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
        if status == "undefined":
            undefined_polls += 1
            if undefined_polls >= UNDEFINED_MAX_POLLS:
                return token_not_found_error(token, attempts=undefined_polls)
            time.sleep(POLL_INTERVAL_SEC)
            continue
        if status in PENDING_STATUSES:
            undefined_polls = 0
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


def save_stage_error(out_dir: Path, filename: str, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def annotate_recoverable_duplicate(client, trigger: dict) -> dict:
    diagnostic = " ".join(str(trigger.get(key, "")) for key in ("message", "description")).casefold()
    if "duplicat" not in diagnostic:
        return trigger

    candidate = trigger.get("token") or trigger.get("candidate_token")
    if not candidate:
        return trigger

    status = None
    for attempt in range(UNDEFINED_MAX_POLLS):
        probe = client.get_result(
            candidate,
            content=False,
            objects=False,
            pages_dict=False,
            pages_tree=False,
        )
        status = probe.get("status") if isinstance(probe, dict) else None
        if status != "undefined" or attempt == UNDEFINED_MAX_POLLS - 1:
            break
        time.sleep(POLL_INTERVAL_SEC)
    trigger["token_status"] = status
    if status == "success" or status in PENDING_STATUSES:
        trigger["recoverable_token"] = candidate
        trigger.pop("candidate_token", None)
        trigger.pop("candidate_token_recoverable", None)
        return trigger

    trigger.pop("token", None)
    trigger["candidate_token"] = candidate
    trigger["candidate_token_recoverable"] = False
    return trigger


def complete_fetch(
    client,
    token: str,
    *,
    out_dir: Path,
    source_stem: str,
) -> dict[str, Any] | int:
    poll_result = poll_until_success(client, token)
    if isinstance(poll_result, int):
        return poll_result

    pages_tree = fetch_pages_tree(client, token)
    if pages_tree.get("status") != "success":
        save_stage_error(out_dir, "pages_tree_error.json", pages_tree)
        return parse_error("get_result_pages_tree", pages_tree)

    formatted = fetch_markdown(client, token)
    if formatted.get("status") != "success":
        save_stage_error(out_dir, "formatted_error.json", formatted)
        return parse_error("get_formatted", formatted)

    summary = save_parse_results(
        out_dir=out_dir,
        source_stem=source_stem,
        pages_tree=pages_tree,
        formatted=formatted,
    )
    summary["token"] = token
    return summary


def run_parse(
    client,
    resolved: ResolvedInput,
    *,
    out_dir: Path,
    trigger_kwargs: dict,
    upload_mode: str = "auto",
) -> dict[str, Any] | int:
    print_parsing_status(display_label_for_input(resolved))
    trigger, stage = trigger_input(client, resolved, trigger_kwargs=trigger_kwargs, upload_mode=upload_mode)
    if trigger.get("status") != "success":
        trigger = annotate_recoverable_duplicate(client, trigger)
        save_stage_error(out_dir, "trigger_error.json", trigger)
        if stage in {"upload_tos", "trigger_file_direct", "trigger_file_fallback"}:
            return upload_error(stage, trigger)
        return parse_error(stage, trigger)

    token = trigger.get("token")
    if not token:
        return parse_error(stage, {"status": "error", "message": "trigger response missing token"})

    meta_path = write_trigger_meta(
        out_dir,
        token=token,
        input_type=resolved.kind.value,
        input_value=resolved.raw,
        trigger_kwargs=serialize_trigger_kwargs(trigger_kwargs),
    )

    summary = complete_fetch(
        client,
        token,
        out_dir=out_dir,
        source_stem=resolved.source_stem,
    )
    if isinstance(summary, int):
        return summary

    summary["input_type"] = resolved.kind.value
    summary["trigger_meta_path"] = str(meta_path)
    return summary

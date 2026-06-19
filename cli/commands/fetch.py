from __future__ import annotations

from pathlib import Path

import click

from cli.core.config import ctx_flag, make_client
from cli.core.errors import missing_token_error
from cli.core.output import (
    default_fetch_output_dir,
    emit_success,
    resolve_output_dir,
    status_line,
)
from cli.core.pipeline import complete_fetch


@click.command("fetch")
@click.option("--token", required=True, help="Task token from a prior successful parse trigger response")
@click.option("--output-dir", "-o", help="Output directory (default: ~/Uni-Parser-Skill/token_<prefix>/)")
@click.option("--overwrite", is_flag=True, help="Overwrite output directory if it already exists")
@click.pass_context
def fetch_cmd(ctx: click.Context, token: str, output_dir: str | None, overwrite: bool) -> None:
    """Poll and download results for an existing job using its token."""
    resolved_token = (token or "").strip()
    if not resolved_token:
        raise SystemExit(missing_token_error())

    client, err = make_client(ctx)
    if err is not None:
        raise SystemExit(err)

    source_stem = f"token_{resolved_token[:8]}"
    if output_dir:
        out_dir, dir_code = resolve_output_dir(source_stem, output_dir, overwrite=overwrite)
    else:
        out = default_fetch_output_dir(resolved_token)
        if out.exists() and not overwrite:
            from cli.core.errors import dir_exists_error

            raise SystemExit(dir_exists_error(out))
        if out.exists() and overwrite:
            import shutil

            shutil.rmtree(out)
        out_dir = out
        dir_code = None

    if dir_code is not None:
        raise SystemExit(dir_code)

    verbose = ctx_flag(ctx, "verbose")

    def on_poll(status: str | None, elapsed: float) -> None:
        if verbose:
            status_line(f"[uniparser] polling… status={status} elapsed={elapsed:.0f}s")

    summary = complete_fetch(
        client,
        resolved_token,
        out_dir=Path(out_dir),
        source_stem=source_stem,
        on_poll=on_poll if verbose else None,
    )
    if isinstance(summary, int):
        raise SystemExit(summary)

    summary["fetched_by_token"] = True
    emit_success(summary, json_output=ctx_flag(ctx, "json_output"))
    raise SystemExit(0)

from __future__ import annotations

import click

from cli.core.config import ctx_flag, make_client
from cli.core.errors import input_error
from cli.core.input import resolve_input
from cli.core.output import emit_success, resolve_output_dir
from cli.core.pipeline import run_parse


@click.command("parse")
@click.argument("source", metavar="INPUT")
@click.option("--output-dir", "-o", help="Output directory (default: ~/Uni-Parser-Skill/<stem>/)")
@click.option("--overwrite", is_flag=True, help="Overwrite output directory if it already exists")
@click.option("--async", "async_mode", is_flag=True, help="Submit with sync=false and poll until success")
@click.pass_context
def parse_cmd(
    ctx: click.Context,
    source: str,
    output_dir: str | None,
    overwrite: bool,
    async_mode: bool,
) -> None:
    """Parse a local PDF/image or public PDF URL; save Markdown and pages_tree."""
    resolved = resolve_input(source)
    if isinstance(resolved, str):
        raise SystemExit(input_error(resolved))

    client, err = make_client(ctx)
    if err is not None:
        raise SystemExit(err)

    out_dir, dir_code = resolve_output_dir(resolved.source_stem, output_dir, overwrite=overwrite)
    if dir_code is not None:
        raise SystemExit(dir_code)

    code = run_parse(
        client,
        resolved,
        out_dir=out_dir,
        async_mode=async_mode,
    )
    if isinstance(code, int):
        raise SystemExit(code)

    emit_success(code, json_output=ctx_flag(ctx, "json_output"))
    raise SystemExit(0)

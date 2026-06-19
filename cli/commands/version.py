from __future__ import annotations

import json

import click

from cli.core.config import ctx_flag, make_client


@click.command("version")
@click.pass_context
def version_cmd(ctx: click.Context) -> None:
    """Print local package version and remote service version."""
    import uniparser_tools

    local_version = uniparser_tools.__version__

    client, err = make_client(ctx)
    if err is not None:
        raise SystemExit(err)

    remote = client.version()

    if ctx_flag(ctx, "json_output"):
        print(
            json.dumps(
                {"local": local_version, "remote": remote},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    else:
        print(f"uniparser-tools: {local_version}")
        remote_status = remote.get("status", remote)
        print(f"remote: {remote_status}")
    raise SystemExit(0)

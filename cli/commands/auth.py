from __future__ import annotations

import click

from cli.core.credentials import CONFIG_PATH, mask_api_key, read_api_key_from_config, save_api_key

API_KEY_URL = "https://uniparser.dp.tech/"


@click.command("auth")
@click.option("--show", is_flag=True, help="Show masked API key from config")
@click.option("--verify", is_flag=True, help="Verify that an API key is configured")
def auth_cmd(show: bool, verify: bool) -> None:
    """Save, inspect, or verify API key configuration."""
    if show:
        api_key = read_api_key_from_config()
        if not api_key:
            print("No API key configured.")
            raise SystemExit(1)
        print(f"API key: {mask_api_key(api_key)}")
        print(f"Config: {CONFIG_PATH}")
        raise SystemExit(0)

    if verify:
        api_key = read_api_key_from_config()
        if not api_key:
            print("No API key configured.")
            raise SystemExit(1)
        print("API key is configured.")
        raise SystemExit(0)

    print("UniParser API Key Setup")
    print(f"Get your API key from: {API_KEY_URL}")
    api_key = click.prompt("Enter your API key", type=str).strip()
    if not api_key:
        print("API key must not be empty.")
        raise SystemExit(1)
    save_api_key(api_key)
    print("API key saved successfully")

#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    private_key = os.getenv("POLY_PRIVATE_KEY", "")
    if not private_key:
        print("POLY_PRIVATE_KEY missing", file=sys.stderr)
        return 1

    clob_host = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
    chain_id = int(os.getenv("POLY_CHAIN_ID", "137"))
    funder = os.getenv("POLY_FUNDER_ADDRESS", "")

    try:
        from py_clob_client.client import ClobClient
    except ImportError as exc:
        print(f"py-clob-client not installed: {exc}", file=sys.stderr)
        return 1

    client = ClobClient(host=clob_host, chain_id=chain_id, key=private_key, funder=funder)

    if hasattr(client, "create_or_derive_api_creds"):
        creds = client.create_or_derive_api_creds()
    elif hasattr(client, "derive_api_creds"):
        creds = client.derive_api_creds()
    elif hasattr(client, "create_api_key"):
        creds = client.create_api_key()
    else:
        print(
            "Unable to derive API credentials with this py-clob-client version. "
            "Expected one of: create_or_derive_api_creds, derive_api_creds, create_api_key",
            file=sys.stderr,
        )
        return 1

    if not isinstance(creds, dict):
        creds = creds.__dict__ if hasattr(creds, "__dict__") else {"value": str(creds)}

    output = {
        "POLY_API_KEY": creds.get("api_key") or creds.get("key") or creds.get("apiKey"),
        "POLY_API_SECRET": creds.get("api_secret") or creds.get("secret") or creds.get("apiSecret"),
        "POLY_API_PASSPHRASE": creds.get("api_passphrase")
        or creds.get("passphrase")
        or creds.get("apiPassphrase"),
    }

    if not all(output.values()):
        print("Could not map derived credentials fields.", file=sys.stderr)
        print(json.dumps(creds, indent=2), file=sys.stderr)
        return 1

    for key, value in output.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

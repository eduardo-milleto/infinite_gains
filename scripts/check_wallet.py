#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal


MAX_USDC_BALANCE = Decimal("150")


def _extract_usdc_balance(payload: dict) -> Decimal | None:
    for key in ("usdc", "USDC", "available_usdc", "balance"):
        if key in payload:
            try:
                return Decimal(str(payload[key]))
            except Exception:
                return None

    nested = payload.get("balances")
    if isinstance(nested, list):
        for entry in nested:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("asset") or entry.get("symbol") or "").upper()
            if symbol == "USDC":
                try:
                    return Decimal(str(entry.get("amount") or entry.get("balance") or 0))
                except Exception:
                    return None
    return None


def main() -> int:
    private_key = os.getenv("POLY_PRIVATE_KEY", "")
    chain_id = int(os.getenv("POLY_CHAIN_ID", "137"))
    host = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
    funder = os.getenv("POLY_FUNDER_ADDRESS", "")

    if not private_key:
        print("POLY_PRIVATE_KEY missing", file=sys.stderr)
        return 1

    try:
        from py_clob_client.client import ClobClient
    except ImportError as exc:
        print(f"py-clob-client not installed: {exc}", file=sys.stderr)
        return 1

    client = ClobClient(host=host, chain_id=chain_id, key=private_key, funder=funder)

    method = None
    for candidate in ("get_balance_allowance", "get_balance", "get_balances"):
        if hasattr(client, candidate):
            method = getattr(client, candidate)
            break

    if method is None:
        print("No compatible balance method found in py-clob-client", file=sys.stderr)
        return 1

    try:
        payload = method()
    except TypeError:
        payload = method({})
    except Exception as exc:
        print(f"Failed to fetch wallet balances: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        payload = payload.__dict__ if hasattr(payload, "__dict__") else {"value": str(payload)}

    usdc_balance = _extract_usdc_balance(payload)
    if usdc_balance is None:
        print("Could not parse USDC balance from response", file=sys.stderr)
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 1

    if usdc_balance > MAX_USDC_BALANCE:
        print(f"USDC balance exceeds safety cap: {usdc_balance} > {MAX_USDC_BALANCE}", file=sys.stderr)
        return 1

    symbols = set()
    balances = payload.get("balances")
    if isinstance(balances, list):
        for entry in balances:
            if isinstance(entry, dict):
                symbol = str(entry.get("asset") or entry.get("symbol") or "").upper()
                if symbol:
                    symbols.add(symbol)
    if symbols and symbols != {"USDC"}:
        print(f"Non-USDC assets found: {sorted(symbols)}", file=sys.stderr)
        return 1

    print(f"Wallet check OK: USDC={usdc_balance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

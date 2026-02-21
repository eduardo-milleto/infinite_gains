from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from src.config.settings import Settings


class PolymarketWalletClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._user_address = settings.poly_funder_address.strip()
        self._data_api = httpx.AsyncClient(
            base_url="https://data-api.polymarket.com",
            timeout=8.0,
            http2=True,
        )
        self._clob_client: Any | None = None

    async def close(self) -> None:
        await self._data_api.aclose()

    async def fetch_snapshot(self) -> dict[str, Any]:
        if not self._user_address:
            return self._empty_snapshot(source="missing_address")

        positions_raw, closed_positions_raw, value_raw = await asyncio.gather(
            self._safe_get_json("/positions", {"user": self._user_address, "limit": 50}),
            self._safe_get_json("/closed-positions", {"user": self._user_address, "limit": 50}),
            self._safe_get_json("/value", {"user": self._user_address}),
        )

        open_positions = self._normalize_positions(positions_raw, is_closed=False)
        closed_positions = self._normalize_positions(closed_positions_raw, is_closed=True)

        holdings_value = self._extract_value(value_raw)
        if holdings_value == Decimal("0"):
            holdings_value = sum((Decimal(str(item["currentValueUsdc"])) for item in open_positions), Decimal("0"))

        cash_balance = await self._fetch_cash_balance_clob()
        total_value = holdings_value + (cash_balance or Decimal("0"))

        return {
            "address": self._user_address,
            "cashUsdc": float(cash_balance) if cash_balance is not None else None,
            "holdingsValueUsdc": float(holdings_value),
            "totalValueUsdc": float(total_value),
            "openPositionsCount": len(open_positions),
            "openPositions": open_positions[:6],
            "closedPositions": closed_positions[:12],
            "updatedAt": datetime.now(tz=timezone.utc).isoformat(),
            "source": "data_api+clob" if cash_balance is not None else "data_api",
        }

    async def _safe_get_json(self, path: str, params: dict[str, Any]) -> Any:
        try:
            response = await self._data_api.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except Exception:
            return []

    @staticmethod
    def _extract_value(payload: Any) -> Decimal:
        if isinstance(payload, dict):
            for key in ("value", "totalValue", "portfolioValue", "amount", "currentValue"):
                raw = payload.get(key)
                if raw is not None:
                    try:
                        return Decimal(str(raw))
                    except Exception:
                        continue
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                extracted = PolymarketWalletClient._extract_value(item)
                if extracted != Decimal("0"):
                    return extracted
        return Decimal("0")

    def _normalize_positions(self, payload: Any, *, is_closed: bool) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []

        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or item.get("market_slug") or item.get("title") or "n/a")
            outcome = str(item.get("outcome") or item.get("position") or "n/a")
            size = self._as_decimal(item.get("size") or item.get("amount") or item.get("shares"))
            avg_price = self._as_decimal(item.get("avgPrice") or item.get("avg_price") or item.get("entryPrice"))
            current_price = self._as_decimal(item.get("curPrice") or item.get("currentPrice") or item.get("markPrice"))
            current_value = self._as_decimal(item.get("currentValue") or item.get("value"))
            cash_pnl = self._as_decimal(item.get("cashPnl") or item.get("realizedPnl") or item.get("pnl"))
            percent_pnl = self._as_decimal(item.get("percentPnl") or item.get("roi") or item.get("returnPercent"))
            updated_at = str(
                item.get("updatedAt")
                or item.get("redeemedAt")
                or item.get("endDate")
                or item.get("createdAt")
                or ""
            )

            rows.append(
                {
                    "slug": slug,
                    "outcome": outcome,
                    "size": float(size),
                    "avgPrice": float(avg_price),
                    "currentPrice": float(current_price),
                    "currentValueUsdc": float(current_value),
                    "cashPnlUsdc": float(cash_pnl),
                    "percentPnl": float(percent_pnl),
                    "updatedAt": updated_at,
                    "isClosed": is_closed,
                }
            )

        rows.sort(key=lambda row: row.get("currentValueUsdc", 0.0), reverse=True)
        return rows

    @staticmethod
    def _as_decimal(value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")

    async def _fetch_cash_balance_clob(self) -> Decimal | None:
        if not self._settings.poly_api_key.get_secret_value():
            return None
        try:
            client = await self._get_or_build_clob_client()
        except Exception:
            return None
        if client is None:
            return None

        methods = [
            "get_balance_allowance",
            "getBalanceAllowance",
            "get_balance",
            "getBalance",
        ]
        for method_name in methods:
            method = getattr(client, method_name, None)
            if method is None:
                continue
            for args in (
                tuple(),
                ({"asset_type": "COLLATERAL"},),
                ({"assetType": "COLLATERAL"},),
            ):
                try:
                    raw = await asyncio.to_thread(method, *args)
                except Exception:
                    continue
                parsed = self._parse_balance(raw)
                if parsed is not None:
                    return parsed
        return None

    async def _get_or_build_clob_client(self) -> Any | None:
        if self._clob_client is not None:
            return self._clob_client
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
        except Exception:
            return None

        private_key = self._settings.poly_private_key.get_secret_value()
        api_creds = ApiCreds(
            api_key=self._settings.poly_api_key.get_secret_value(),
            api_secret=self._settings.poly_api_secret.get_secret_value(),
            api_passphrase=self._settings.poly_api_passphrase.get_secret_value(),
        )
        try:
            self._clob_client = ClobClient(
                host=self._settings.poly_clob_host,
                chain_id=self._settings.poly_chain_id,
                key=private_key,
                creds=api_creds,
                funder=self._settings.poly_funder_address,
            )
        except TypeError:
            self._clob_client = ClobClient(
                self._settings.poly_clob_host,
                self._settings.poly_chain_id,
                private_key,
            )
        return self._clob_client

    @staticmethod
    def _parse_balance(payload: Any) -> Decimal | None:
        if isinstance(payload, (int, float, str, Decimal)):
            try:
                return Decimal(str(payload))
            except Exception:
                return None
        if isinstance(payload, dict):
            for key in ("balance", "available", "allowance", "usdc", "amount"):
                raw = payload.get(key)
                if raw is None:
                    continue
                try:
                    return Decimal(str(raw))
                except Exception:
                    continue
        return None

    def _empty_snapshot(self, *, source: str) -> dict[str, Any]:
        return {
            "address": self._user_address or "n/a",
            "cashUsdc": None,
            "holdingsValueUsdc": 0.0,
            "totalValueUsdc": 0.0,
            "openPositionsCount": 0,
            "openPositions": [],
            "closedPositions": [],
            "updatedAt": datetime.now(tz=timezone.utc).isoformat(),
            "source": source,
        }

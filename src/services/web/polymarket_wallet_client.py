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
        self._owner_address = settings.poly_funder_address.strip()
        self._query_address = self._owner_address
        self._data_api = httpx.AsyncClient(
            base_url="https://data-api.polymarket.com",
            timeout=8.0,
            http2=True,
        )
        self._gamma_api = httpx.AsyncClient(
            base_url="https://gamma-api.polymarket.com",
            timeout=8.0,
            http2=True,
        )
        self._clob_client: Any | None = None
        self._clob_client_address: str | None = None

    async def close(self) -> None:
        await self._data_api.aclose()
        await self._gamma_api.aclose()

    async def fetch_snapshot(self) -> dict[str, Any]:
        if not self._owner_address:
            return self._empty_snapshot(source="missing_address")

        query_address = await self._resolve_query_address()

        positions_raw, closed_positions_raw, value_raw = await asyncio.gather(
            self._safe_get_json("/positions", {"user": query_address, "limit": 100, "sizeThreshold": 0}),
            self._safe_get_json("/closed-positions", {"user": query_address, "limit": 100}),
            self._safe_get_json("/value", {"user": query_address}),
        )

        open_positions = self._normalize_positions(positions_raw, is_closed=False)
        open_positions = [
            row
            for row in open_positions
            if (row["size"] > 0 and (row["currentValueUsdc"] > 0.0001 or row["currentPrice"] > 0))
        ]
        closed_positions = self._normalize_positions(closed_positions_raw, is_closed=True)

        holdings_value = self._extract_value(value_raw)
        if holdings_value == Decimal("0"):
            holdings_value = sum((Decimal(str(item["currentValueUsdc"])) for item in open_positions), Decimal("0"))

        cash_balance = await self._fetch_cash_balance_clob(query_address=query_address)
        total_value = holdings_value + (cash_balance or Decimal("0"))

        return {
            "address": query_address or self._owner_address,
            "cashUsdc": float(cash_balance) if cash_balance is not None else None,
            "holdingsValueUsdc": float(holdings_value),
            "totalValueUsdc": float(total_value),
            "openPositionsCount": len(open_positions),
            "openPositions": open_positions[:6],
            "closedPositions": closed_positions[:12],
            "updatedAt": datetime.now(tz=timezone.utc).isoformat(),
            "source": self._build_source_tag(cash_balance=cash_balance, query_address=query_address),
        }

    async def _safe_get_json(self, path: str, params: dict[str, Any]) -> Any:
        try:
            response = await self._data_api.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except Exception:
            return []

    async def _resolve_query_address(self) -> str:
        owner = self._owner_address
        if not owner:
            return owner

        try:
            response = await self._gamma_api.get("/public-profile", params={"address": owner})
            response.raise_for_status()
            payload = response.json()
        except Exception:
            self._query_address = owner
            return owner

        proxy_wallet = self._extract_proxy_wallet(payload)
        self._query_address = proxy_wallet or owner
        return self._query_address

    @staticmethod
    def _extract_proxy_wallet(payload: Any) -> str:
        if isinstance(payload, dict):
            candidate = payload.get("proxyWallet")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            for value in payload.values():
                extracted = PolymarketWalletClient._extract_proxy_wallet(value)
                if extracted:
                    return extracted
        if isinstance(payload, list):
            for item in payload:
                extracted = PolymarketWalletClient._extract_proxy_wallet(item)
                if extracted:
                    return extracted
        return ""

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
            size = self._as_decimal(
                item.get("size")
                or item.get("amount")
                or item.get("shares")
                or item.get("positionSize")
                or item.get("position_size")
            )
            avg_price = self._as_decimal(item.get("avgPrice") or item.get("avg_price") or item.get("entryPrice"))
            current_price = self._as_decimal(
                item.get("curPrice") or item.get("currentPrice") or item.get("markPrice") or item.get("price")
            )
            current_value = self._as_decimal(
                item.get("currentValue")
                or item.get("currentValueUsdc")
                or item.get("current_value")
                or item.get("value")
            )
            if current_value == Decimal("0") and size > 0 and current_price > 0:
                current_value = size * current_price
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

    async def _fetch_cash_balance_clob(self, *, query_address: str) -> Decimal | None:
        if not self._settings.poly_api_key.get_secret_value():
            return None
        try:
            client = await self._get_or_build_clob_client(query_address=query_address)
        except Exception:
            return None
        if client is None:
            return None

        signature_type = self._settings.poly_signature_type
        raw_params = (
            {"asset_type": "COLLATERAL", "signature_type": signature_type},
            {"assetType": "COLLATERAL", "signatureType": signature_type},
            {"asset_type": "COLLATERAL"},
            {"assetType": "COLLATERAL"},
        )

        for method_name in ("update_balance_allowance", "updateBalanceAllowance"):
            method = getattr(client, method_name, None)
            if method is None:
                continue
            for params in raw_params:
                for args, kwargs in (((params,), {}), (tuple(), {"params": params})):
                    try:
                        await asyncio.to_thread(method, *args, **kwargs)
                    except Exception:
                        continue

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
            for params in raw_params:
                for args, kwargs in (((params,), {}), (tuple(), {"params": params})):
                    try:
                        raw = await asyncio.to_thread(method, *args, **kwargs)
                    except Exception:
                        continue
                    parsed = self._parse_balance(raw)
                    if parsed is not None:
                        return parsed
        return None

    async def _get_or_build_clob_client(self, *, query_address: str) -> Any | None:
        if self._clob_client is not None and self._clob_client_address == query_address:
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
        builders = (
            {
                "host": self._settings.poly_clob_host,
                "chain_id": self._settings.poly_chain_id,
                "key": private_key,
                "creds": api_creds,
                "funder": query_address,
                "signature_type": self._settings.poly_signature_type,
            },
            {
                "host": self._settings.poly_clob_host,
                "chain_id": self._settings.poly_chain_id,
                "key": private_key,
                "creds": api_creds,
                "funder": query_address,
            },
        )
        client: Any | None = None
        for kwargs in builders:
            try:
                client = ClobClient(**kwargs)
                break
            except TypeError:
                continue
        if client is None:
            try:
                client = ClobClient(
                    self._settings.poly_clob_host,
                    self._settings.poly_chain_id,
                    private_key,
                )
            except Exception:
                return None

        self._clob_client = client
        self._clob_client_address = query_address
        return self._clob_client

    @staticmethod
    def _parse_balance(payload: Any) -> Decimal | None:
        if isinstance(payload, (int, float, str, Decimal)):
            return PolymarketWalletClient._normalize_usdc_amount(PolymarketWalletClient._as_decimal(payload))
        if isinstance(payload, dict):
            for key in ("balance", "available", "allowance", "usdc", "amount"):
                raw = payload.get(key)
                if raw is None:
                    continue
                normalized = PolymarketWalletClient._parse_balance(raw)
                if normalized is not None:
                    return normalized
            for value in payload.values():
                normalized = PolymarketWalletClient._parse_balance(value)
                if normalized is not None:
                    return normalized
        if isinstance(payload, list):
            for item in payload:
                normalized = PolymarketWalletClient._parse_balance(item)
                if normalized is not None:
                    return normalized
        return None

    @staticmethod
    def _normalize_usdc_amount(value: Decimal) -> Decimal | None:
        if value < 0:
            return None
        # CLOB often returns USDC amounts in base units (6 decimals).
        if value == value.to_integral_value() and value >= Decimal("10000"):
            scaled = value / Decimal("1000000")
            if scaled >= 0:
                return scaled
        return value

    def _build_source_tag(self, *, cash_balance: Decimal | None, query_address: str) -> str:
        parts = ["data_api"]
        if query_address and query_address.lower() != self._owner_address.lower():
            parts.append("proxy_wallet")
        if cash_balance is not None:
            parts.append("clob")
        return "+".join(parts)

    def _empty_snapshot(self, *, source: str) -> dict[str, Any]:
        return {
            "address": self._owner_address or "n/a",
            "cashUsdc": None,
            "holdingsValueUsdc": 0.0,
            "totalValueUsdc": 0.0,
            "openPositionsCount": 0,
            "openPositions": [],
            "closedPositions": [],
            "updatedAt": datetime.now(tz=timezone.utc).isoformat(),
            "source": source,
        }

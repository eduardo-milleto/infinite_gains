#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from src.config.settings import get_settings
from src.db.engine import Database
from src.db.repository import SignalRepo
from src.services.indicators.signal_engine import SignalEngine
from src.services.indicators.taapi_client import TaapiClient


async def run_backfill(iterations: int) -> None:
    settings = get_settings()
    database = Database(settings)
    taapi_client = TaapiClient(settings)
    signal_engine = SignalEngine(settings)

    try:
        for _ in range(iterations):
            snapshot = await taapi_client.fetch_snapshot()
            signal = signal_engine.evaluate(snapshot)
            async with database.session() as session:
                repo = SignalRepo(session)
                await repo.create(
                    snapshot=snapshot,
                    signal_type=signal.signal_type,
                    filter_result=signal.reason,
                    market_slug="backfill",
                    spread_at_eval=None,
                    trading_mode=settings.trading_mode,
                )
            print(
                f"stored signal: candle={snapshot.candle_open_utc.isoformat()} "
                f"type={signal.signal_type.value}"
            )
    finally:
        await taapi_client.close()
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill recent TA snapshots into signals table")
    parser.add_argument("--iterations", type=int, default=24, help="How many snapshots to fetch")
    args = parser.parse_args()

    asyncio.run(run_backfill(args.iterations))


if __name__ == "__main__":
    main()

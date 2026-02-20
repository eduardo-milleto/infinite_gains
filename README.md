# Infinite Gains

Polymarket BTC 1H bot with TAAPI-based RSI/Stochastic signals, risk gating, paper/live execution paths, Telegram control, and daily learning proposals.

## Quick start

1. Copy env template:

```bash
cp .env.example .env
```

2. Fill required secrets in `.env`.

3. Start stack:

```bash
docker compose up --build
```

4. Optional monitoring overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up --build
```

## Local commands

```bash
make install
make migrate
make run-trader
make run-telegram
make run-learning
make test
```

## Safety scripts

```bash
python scripts/generate_l2_keys.py
python scripts/check_wallet.py
python scripts/backfill_signals.py --iterations 24
```

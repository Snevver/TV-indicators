#!/usr/bin/env bash
# Sanity suite for the backtester. Every case below has a known correct answer,
# so if one of them stops holding, the simulator is broken — not the market.
set -euo pipefail
cd "$(dirname "$0")"
G="Trades  |Win rate|Total R|Expectancy|Profit factor|Result|t-statistic"

echo "1. RANDOM WALK — must land near zero, slightly negative from costs."
python3 backtest.py --synthetic random --bars 30000 --seed 7 --stability 0.3 --rsi-index 60 --gap 3 | grep -E "$G"

echo; echo "2. MEAN-REVERTING — the indicator's home turf, must show a positive edge."
python3 backtest.py --synthetic meanrevert --bars 30000 --seed 3 --stability 0.3 --rsi-index 60 --gap 3 | grep -E "$G"

echo; echo "3. TRENDING, counter-trend mode — must bleed."
python3 backtest.py --synthetic trend --bars 30000 --seed 3 --stability 0.3 --rsi-index 60 --gap 3 | grep -E "$G"

echo; echo "4. ZERO COSTS on a random walk — must be closer to zero than case 1."
python3 backtest.py --synthetic random --bars 30000 --seed 7 --stability 0.3 --rsi-index 60 --gap 3 \
    --fee-bps 0 --slippage-bps 0 | grep -E "Expectancy|Total R"

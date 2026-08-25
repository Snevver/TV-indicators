#!/usr/bin/env bash
# Reproduces every gold number quoted in README.md.
set -euo pipefail
cd "$(dirname "$0")"
G="Bars |Signals fired|Trades  |Win rate|Total R|Expectancy|Profit factor|Equity|Max draw|Buy & hold|Result|t-statis"

python3 fetch_data.py            # no-op once cached

echo; echo "### 1. Gold, DEFAULT settings — note the signal count."
for f in XAUUSD_d1 XAUUSD_h4 XAUUSD_h1; do
  echo "--- $f"; python3 backtest.py --csv "data/$f.csv" | grep -E "$G"
done

echo; echo "### 2. Gold hourly, loosened until the sample is meaningful."
python3 backtest.py --csv data/XAUUSD_h1.csv --stability 0.3 --rsi-index 60 --gap 3 | grep -E "$G"

echo; echo "### 3. Does ANY parameter set work on gold?"
python3 backtest.py --csv data/XAUUSD_h1.csv --stability 0.3 --rsi-index 60 --gap 3 \
    --sweep --min-trades 40 | tail -25

echo; echo "### 4. Do the winners survive data they were not chosen on?"
python3 backtest.py --csv data/XAUUSD_h1.csv --stability 0.3 --rsi-index 60 --gap 3 \
    --walk-forward --min-trades 40 | tail -20

"""Bundled, static showcase results. Not forecasts or active market signals."""
from pathlib import Path
import json
import pandas as pd

ASSETS = Path(__file__).resolve().parent / 'assets'

def showcase():
    return json.loads((ASSETS / 'demo_metrics.json').read_text(encoding='utf-8'))

def historical_spot_chart():
    prices = pd.read_csv(ASSETS / 'demo_spot_2025_daily.csv')
    prices['date'] = pd.to_datetime(prices['date'])
    return prices

def strategies():
    return pd.DataFrame(showcase()['strategy_2025_q4']['results'])

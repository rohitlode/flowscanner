"""
Runs MACD + RSI + Volume-breakout strategies on 1y daily OHLCV via yfinance.
Stores results in backtest_results table and re-classifies test_bucket.
"""
import yfinance as yf
import pandas as pd
import uuid, db
from datetime import datetime


# ── strategy engines ──────────────────────────────────────────────────────────

def _macd_strategy(df: pd.DataFrame) -> list[dict]:
    close = df["Close"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    sig   = macd.ewm(span=9, adjust=False).mean()
    trades, pos, entry = [], False, 0.0
    for i in range(1, len(df)):
        if not pos and macd.iloc[i] > sig.iloc[i] and macd.iloc[i-1] <= sig.iloc[i-1]:
            pos, entry = True, close.iloc[i]
        elif pos and macd.iloc[i] < sig.iloc[i] and macd.iloc[i-1] >= sig.iloc[i-1]:
            trades.append((entry, close.iloc[i]))
            pos = False
    if pos:
        trades.append((entry, close.iloc[-1]))
    return trades


def _rsi_strategy(df: pd.DataFrame, oversold=35, overbought=65) -> list[dict]:
    close  = df["Close"]
    delta  = close.diff()
    gain   = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss   = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rs     = gain / loss.replace(0, 1e-9)
    rsi    = 100 - (100 / (1 + rs))
    trades, pos, entry = [], False, 0.0
    for i in range(1, len(df)):
        if not pos and rsi.iloc[i] < oversold:
            pos, entry = True, close.iloc[i]
        elif pos and rsi.iloc[i] > overbought:
            trades.append((entry, close.iloc[i]))
            pos = False
    if pos:
        trades.append((entry, close.iloc[-1]))
    return trades


def _vol_breakout_strategy(df: pd.DataFrame) -> list[dict]:
    close   = df["Close"]
    vol     = df["Volume"]
    avg_vol = vol.rolling(20).mean()
    trades, pos, entry, hold = [], False, 0.0, 0
    for i in range(20, len(df)):
        chg = (close.iloc[i] - close.iloc[i-1]) / close.iloc[i-1]
        if not pos and vol.iloc[i] > avg_vol.iloc[i] * 2 and chg > 0.02:
            pos, entry, hold = True, close.iloc[i], 0
        elif pos:
            hold += 1
            stop  = entry * 0.95
            tp    = entry * 1.10
            if close.iloc[i] <= stop or close.iloc[i] >= tp or hold >= 7:
                trades.append((entry, close.iloc[i]))
                pos = False
    if pos:
        trades.append((entry, close.iloc[-1]))
    return trades


def _metrics(trades: list) -> dict:
    if not trades:
        return {"n_trades": 0, "win_rate": 0.0, "avg_return_pct": 0.0, "total_return_pct": 0.0}
    rets   = [(s - e) / e * 100 for e, s in trades]
    wins   = [r for r in rets if r > 0]
    equity = 10000.0
    for e, s in trades:
        equity *= s / e
    return {
        "n_trades":        len(trades),
        "win_rate":        round(len(wins) / len(trades), 3),
        "avg_return_pct":  round(sum(rets) / len(rets), 2),
        "total_return_pct": round((equity - 10000) / 100, 2),
    }


# ── public API ────────────────────────────────────────────────────────────────

def run_backtest(ticker: str, period: str = "1y"):
    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 30:
            return None
        # flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    except Exception as e:
        print(f"yfinance error {ticker}: {e}")
        return None

    results = {}
    for name, fn in [("macd", _macd_strategy), ("rsi", _rsi_strategy), ("vol_breakout", _vol_breakout_strategy)]:
        try:
            trades = fn(df)
            results[name] = _metrics(trades)
        except Exception as e:
            print(f"Strategy {name} error on {ticker}: {e}")
            results[name] = {"n_trades": 0, "win_rate": 0.0, "avg_return_pct": 0.0, "total_return_pct": 0.0}

    # pick best by total_return
    best_name = max(results, key=lambda k: results[k]["total_return_pct"])
    best      = results[best_name]

    # classify test_bucket from real backtest data
    wr = best["win_rate"]
    nt = best["n_trades"]
    tr = best["total_return_pct"]
    if nt >= 8 and wr >= 0.55 and tr > 0:
        test_bucket = "VALIDATED_TEST"
    elif nt >= 5 and wr >= 0.45:
        test_bucket = "WATCH"
    else:
        test_bucket = "UNVALIDATED"

    return {
        "ticker":          ticker,
        "period":          period,
        "best_strategy":   best_name,
        "win_rate":        best["win_rate"],
        "n_trades":        best["n_trades"],
        "avg_return_pct":  best["avg_return_pct"],
        "total_return_pct": best["total_return_pct"],
        "macd":            results["macd"],
        "rsi":             results["rsi"],
        "vol_breakout":    results["vol_breakout"],
        "test_bucket":     test_bucket,
        "run_at":          datetime.utcnow().isoformat(),
    }


def backtest_and_store(ticker: str):
    result = run_backtest(ticker)
    if not result:
        return None
    db.upsert_backtest(result)
    # update any active signal's test_bucket to match real data
    db.update_signal_test_bucket(ticker, result["test_bucket"])
    return result


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    r = run_backtest(ticker)
    if r:
        print(f"\n{ticker} — best: {r['best_strategy']} | win_rate: {r['win_rate']:.0%} | "
              f"trades: {r['n_trades']} | avg: {r['avg_return_pct']:+.1f}% | "
              f"total: {r['total_return_pct']:+.1f}% → {r['test_bucket']}")
        print(f"  MACD:          {r['macd']}")
        print(f"  RSI:           {r['rsi']}")
        print(f"  Vol Breakout:  {r['vol_breakout']}")

"""
Direct TradingView screener calls — no MCP needed.
The MCP is just a wrapper around these same endpoints.
"""
from __future__ import annotations
import httpx
import uuid
from datetime import datetime
import config

TV_SCAN_URL = "https://scanner.tradingview.com/america/scan"
TV_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

COLUMNS = [
    "name", "close", "change", "volume", "relative_volume_10d_calc",
    "RSI", "BB.upper", "BB.lower", "EMA200", "MACD.macd", "MACD.signal",
    "SMA20", "average_volume_10d_calc",
]

PUT_RISK_OFF_TICKERS = {
    "SPY","QQQ","IWM","DIA","XLK","AAPL","MSFT","NVDA","AMZN","GOOGL",
    "META","SMH","GLD","TLT","XLF","XLE","XBI",
}


def _classify(row: dict) -> dict:
    ticker   = row["ticker"]
    chg      = row.get("change_pct", 0)
    rsi      = row.get("rsi", 50)
    vol_r    = row.get("volume_ratio", 1)
    macd     = row.get("macd", 0)
    macd_sig = row.get("macd_signal", 0)
    price    = row.get("price", 0)
    ema200   = row.get("ema200") or 0

    bullish  = chg > 0 and rsi > 50 and macd > macd_sig
    bearish  = chg < 0 and macd < macd_sig

    # Honest classification — technical signal only, no options data yet.
    # Upgraded to CALL_SWEEP / PUT_RISK_OFF by ingest_ibkr.py when IBKR confirms real flow.
    if bearish:
        flow_strategy = "BEARISH_TECHNICAL"
    else:
        flow_strategy = "BULLISH_TECHNICAL"

    # net score proxy
    score = 0
    if bullish or bearish:
        score += 1
    if vol_r >= 3:
        score += 1
    if abs(chg) >= 4:
        score += 1
    if rsi < 35 or rsi > 65:
        score += 1

    if score >= 2:
        test_bucket = "WATCH"
    else:
        test_bucket = "UNVALIDATED"

    # OI behavior: never fabricate — real OI requires options data
    oi_behavior = None

    confidence = min(95, 40 + score * 15)

    return {
        "flow_strategy": flow_strategy,
        "test_bucket": test_bucket,
        "oi_behavior": oi_behavior,
        "confidence": confidence,
        "direction": "long" if flow_strategy == "BULLISH_TECHNICAL" else "short",
    }


def _build_payload(exchange: str, min_vol_ratio: float, min_change: float, limit: int) -> dict:
    mkt = "america"
    return {
        "filter": [
            {"left": "exchange",                   "operation": "equal",           "right": exchange},
            {"left": "relative_volume_10d_calc",   "operation": "greater",         "right": min_vol_ratio},
            {"left": "change",                     "operation": "greater",         "right": min_change},
            {"left": "close",                      "operation": "greater",         "right": 3},
            {"left": "average_volume_10d_calc",    "operation": "greater",         "right": 50000},
        ],
        "options": {"lang": "en"},
        "columns": COLUMNS,
        "sort": {"sortBy": "relative_volume_10d_calc", "sortOrder": "desc"},
        "range": [0, limit],
    }


def _build_bearish_payload(exchange: str, limit: int) -> dict:
    return {
        "filter": [
            {"left": "exchange",                   "operation": "equal",    "right": exchange},
            {"left": "relative_volume_10d_calc",   "operation": "greater",  "right": 2},
            {"left": "change",                     "operation": "less",     "right": -2.0},
            {"left": "close",                      "operation": "greater",  "right": 5},
            {"left": "average_volume_10d_calc",    "operation": "greater",  "right": 200000},
        ],
        "options": {"lang": "en"},
        "columns": COLUMNS,
        "sort": {"sortBy": "relative_volume_10d_calc", "sortOrder": "desc"},
        "range": [0, limit],
    }


def _parse_rows(data: dict, exchange: str) -> list[dict]:
    results = []
    for item in data.get("data", []):
        cols = item.get("d", [])
        if len(cols) < len(COLUMNS):
            continue
        ticker = cols[0]
        row = {
            "ticker":        ticker,
            "exchange":      exchange,
            "price":         cols[1],
            "change_pct":    cols[2],
            "volume":        cols[3],
            "volume_ratio":  cols[4],
            "rsi":           cols[5],
            "bb_upper":      cols[6],
            "bb_lower":      cols[7],
            "ema200":        cols[8],
            "macd":          cols[9],
            "macd_signal":   cols[10],
            "sma20":         cols[11],
            "avg_volume":    cols[12],
        }
        results.append(row)
    return results


def run_scan(exchanges=("NASDAQ", "NYSE"), min_vol_ratio=2.0, min_change=2.0, limit=15) -> list[dict]:
    signals = []
    candidates = 0

    with httpx.Client(timeout=15) as client:
        for exchange in exchanges:
            # bullish sweep
            try:
                r = client.post(TV_SCAN_URL, json=_build_payload(exchange, min_vol_ratio, min_change, limit), headers=TV_HEADERS)
                r.raise_for_status()
                rows = _parse_rows(r.json(), exchange)
                candidates += r.json().get("totalCount", len(rows))
                for row in rows:
                    cls = _classify(row)
                    sig = {**row, **cls,
                        "id": str(uuid.uuid4()),
                        "analysis_summary": f"Vol {row['volume_ratio']:.1f}x avg | RSI {row.get('rsi',0):.0f} | Chg {row['change_pct']:.1f}% | {cls['flow_strategy']}",
                    }
                    from conviction import score_conviction
                    sig = score_conviction(sig, run_ah_check=False)
                    signals.append(sig)
            except Exception as e:
                print(f"Bullish scan error ({exchange}): {e}")

            # bearish (PUT_RISK_OFF candidates)
            try:
                r = client.post(TV_SCAN_URL, json=_build_bearish_payload(exchange, limit), headers=TV_HEADERS)
                r.raise_for_status()
                rows = _parse_rows(r.json(), exchange)
                for row in rows:
                    cls = _classify(row)
                    if cls["flow_strategy"] == "FLOW_REPEAT_SWEEP_PUT_RISK_OFF":
                        sig = {**row, **cls,
                            "id": str(uuid.uuid4()),
                            "analysis_summary": f"Vol {row['volume_ratio']:.1f}x avg | RSI {row.get('rsi',0):.0f} | Chg {row['change_pct']:.1f}% | Bearish sweep detected",
                        }
                        from conviction import score_conviction
                        sig = score_conviction(sig, run_ah_check=False)
                        signals.append(sig)
            except Exception as e:
                print(f"Bearish scan error ({exchange}): {e}")

    # dedupe by ticker, keep highest confidence
    seen = {}
    for s in signals:
        t = s["ticker"]
        if t not in seen or s["confidence"] > seen[t]["confidence"]:
            seen[t] = s

    result = list(seen.values())
    result.sort(key=lambda x: x["confidence"], reverse=True)
    return result[:20], candidates


def analyze_ticker(ticker: str) -> dict:
    """
    Full flow analysis for a single ticker.
    Uses yfinance for OHLCV + volume metrics, then classifies signal.
    Returns signal dict or raises ValueError with reason.
    """
    import yfinance as yf
    import pandas as pd

    t = ticker.upper()
    info = yf.Ticker(t)

    # 1y daily for volume ratio + technicals
    df = info.history(period="3mo", interval="1d")
    if df is None or len(df) < 20:
        raise ValueError(f"Insufficient price history for {t}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close     = float(df["Close"].iloc[-1])
    prev      = float(df["Close"].iloc[-2])
    volume    = float(df["Volume"].iloc[-1])
    avg_vol   = float(df["Volume"].rolling(10).mean().iloc[-1])
    vol_ratio = volume / avg_vol if avg_vol > 0 else 1.0
    chg_pct   = (close - prev) / prev * 100

    if close < 1.0:
        raise ValueError(f"{t} price ${close:.3f} too low (< $1)")

    # RSI
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rs    = gain / loss.replace(0, 1e-9)
    rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

    # MACD
    ema12     = df["Close"].ewm(span=12, adjust=False).mean()
    ema26     = df["Close"].ewm(span=26, adjust=False).mean()
    macd_val  = float((ema12 - ema26).iloc[-1])
    macd_sig  = float((ema12 - ema26).ewm(span=9, adjust=False).mean().iloc[-1])

    # EMA200 (use 50 if not enough history)
    ema_span  = min(200, len(df) - 1)
    ema200    = float(df["Close"].ewm(span=ema_span, adjust=False).mean().iloc[-1])

    row = {
        "ticker":       t,
        "exchange":     "NASDAQ",
        "price":        round(close, 2),
        "change_pct":   round(chg_pct, 2),
        "volume_ratio": round(vol_ratio, 2),
        "rsi":          round(rsi, 1),
        "macd":         macd_val,
        "macd_signal":  macd_sig,
        "ema200":       ema200,
    }
    cls = _classify(row)

    # Derived signal fields
    rsi_signal = "oversold" if rsi < 35 else ("overbought" if rsi > 65 else "neutral")
    macd_signal_dir = "bullish" if macd_val > macd_sig else "bearish"
    price_vs_ema = "above" if close > ema200 else "below"
    sentiment = "Pending — run combined_analysis in Claude Code for full sentiment"

    # News — call underlying service directly (same code the MCP tool uses)
    news_note = ""
    try:
        import sys
        sys.path.insert(0, config.TV_MCP_SRC)
        from tradingview_mcp.core.services.news_service import fetch_news
        articles = fetch_news(symbol=t, category="stocks", limit=3)
        if articles:
            news_note = "\nNews (FYI only): " + " | ".join(a["title"][:70] for a in articles[:2])
    except Exception:
        pass

    analysis_summary = (
        f"RSI {rsi:.1f} ({rsi_signal}) | "
        f"MACD {macd_signal_dir} | "
        f"Vol {vol_ratio:.1f}x avg | "
        f"Price {'above' if price_vs_ema == 'above' else 'below'} EMA{ema_span} | "
        f"Chg {chg_pct:+.1f}% | {cls['flow_strategy']}"
        f"{news_note}"
    )

    sig = {
        **row,
        **cls,
        "id":               str(uuid.uuid4()),
        "rsi_signal":       rsi_signal,
        "macd_signal_dir":  macd_signal_dir,
        "price_vs_ema":     price_vs_ema,
        "sentiment":        sentiment,
        "analysis_summary": analysis_summary,
    }

    # Conviction tier (runs AH fade check)
    from conviction import score_conviction
    sig = score_conviction(sig, run_ah_check=True)
    return sig


if __name__ == "__main__":
    sigs, total = run_scan()
    print(f"Found {len(sigs)} signals from {total} candidates")
    for s in sigs:
        print(f"  {s['ticker']:6} {s['flow_strategy']:40} {s['test_bucket']:15} conf={s['confidence']}")

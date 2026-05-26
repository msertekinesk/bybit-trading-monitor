#!/usr/bin/env python3
import os
import json
import time
import hmac
import hashlib
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
BYBIT_API_KEY    = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

BASE_URL = "https://data-api.binance.vision"

WATCHLIST_BY_CATEGORY = {
    "MAJORS":   ["BTCUSDT", "ETHUSDT"],
    "L1 ALTS":  ["SOLUSDT", "BNBUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "SUIUSDT", "ADAUSDT", "TRXUSDT"],
    "DEFI":     ["LINKUSDT", "UNIUSDT", "DOTUSDT"],
    "STORIES":  ["TONUSDT", "HBARUSDT", "ATOMUSDT", "XLMUSDT", "XRPUSDT"],
    "MEMES":    ["DOGEUSDT"],
    "LEGACY":   ["LTCUSDT"],
}

WATCHLIST = [coin for coins in WATCHLIST_BY_CATEGORY.values() for coin in coins]
TIMEFRAMES = ["15m", "1h", "4h"]

DECISIONS_FILE = os.path.join(os.path.dirname(__file__), "decisions.jsonl")
TZ_LOCAL = timezone(timedelta(hours=3))

# ── Signing helper (private endpoints) ───────────────────────────────────────
def _sign(params: dict) -> dict:
    ts = str(int(time.time() * 1000))
    recv_window = "5000"
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    raw = f"{ts}{BYBIT_API_KEY}{recv_window}{query}"
    sig = hmac.new(BYBIT_API_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    params.update({"api_key": BYBIT_API_KEY, "timestamp": ts,
                   "recv_window": recv_window, "sign": sig})
    return params


# ── Binance kline ─────────────────────────────────────────────────────────────
def get_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    rows = resp.json()
    df = pd.DataFrame(rows, columns=[
        "ts", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_numeric(df["ts"])
    return df


# ── Indicators ────────────────────────────────────────────────────────────────
def calc_ema50(closes: pd.Series) -> float:
    k = 2 / 51
    ema = closes.iloc[0]
    for price in closes.iloc[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def calc_rsi14(closes: pd.Series) -> float:
    diffs = closes.diff().dropna()
    gains  = diffs.clip(lower=0)
    losses = (-diffs).clip(lower=0)
    avg_gain = gains.iloc[:14].mean()
    avg_loss = losses.iloc[:14].mean()
    for g, l in zip(gains.iloc[14:], losses.iloc[14:]):
        avg_gain = g * (1 / 14) + avg_gain * (13 / 14)
        avg_loss = l * (1 / 14) + avg_loss * (13 / 14)
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def evaluate_bias(price: float, ema50: float, rsi: float) -> str:
    above = price > ema50
    if above and 45 <= rsi <= 70:
        return "bullish"
    if not above and 30 <= rsi <= 55:
        return "bearish"
    return "neutral"


def consensus_bias(tf_biases: dict) -> str:
    biases = list(tf_biases.values())
    bull = biases.count("bullish")
    bear = biases.count("bearish")
    if bull == 3:   return "STRONG BULLISH"
    if bear == 3:   return "STRONG BEARISH"
    if bull == 2:   return "BULLISH"
    if bear == 2:   return "BEARISH"
    return "MIXED"


def volume_signal(df: pd.DataFrame) -> str:
    last_vol = df["volume"].iloc[-1]
    avg_20   = df["volume"].iloc[-21:-1].mean()
    ratio    = last_vol / avg_20 if avg_20 > 0 else 0
    if ratio >= 1.5:  return "HIGH VOL"
    if ratio <= 0.5:  return "LOW VOL"
    return "NORMAL VOL"


# ── Formatting ────────────────────────────────────────────────────────────────
def fmt_price(symbol: str, price: float) -> str:
    if symbol in ("BTCUSDT",):
        return f"${price:,.2f}"
    if symbol in ("ETHUSDT", "BNBUSDT", "SOLUSDT", "LTCUSDT"):
        return f"${price:.2f}"
    if price >= 1:
        return f"${price:.4f}"
    if price >= 0.01:
        return f"${price:.4f}"
    return f"${price:.6f}"


# ── Telegram ──────────────────────────────────────────────────────────────────
def telegram_send(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [WARN] Telegram credentials eksik.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.json().get("ok"):
            print("  [OK] Telegram gönderildi.")
        else:
            print(f"  [ERR] Telegram: {r.json()}")
    except Exception as e:
        print(f"  [ERR] Telegram isteği başarısız: {e}")


def telegram_send_long(text: str) -> None:
    """4096 karakter aşılırsa ikiye böl."""
    if len(text) <= 4096:
        telegram_send(text)
        return
    # Satır sınırında kes
    mid = text.rfind("\n", 0, 4000)
    if mid == -1:
        mid = 4000
    telegram_send(text[:mid])
    telegram_send(text[mid:].lstrip("\n"))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now      = datetime.now(TZ_LOCAL)
    ts_str   = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    ts_label = now.strftime("%Y-%m-%d %H:%M UTC+3")
    print(f"\n=== SNAPSHOT {ts_label} ===\n")

    results_by_symbol = {}
    errors = []

    for symbol in WATCHLIST:
        print(f"[{symbol}]")
        try:
            tf_dfs    = {}
            tf_biases = {}
            tf_rsi    = {}

            for tf in TIMEFRAMES:
                df = get_klines(symbol, interval=tf, limit=200)
                closes = df["close"]
                price  = closes.iloc[-1]
                ema50  = calc_ema50(closes)
                rsi14  = calc_rsi14(closes)
                bias   = evaluate_bias(price, ema50, rsi14)
                tf_dfs[tf]    = df
                tf_biases[tf] = bias
                tf_rsi[tf]    = rsi14

            consensus   = consensus_bias(tf_biases)
            vol_signal  = volume_signal(tf_dfs["15m"])
            df_15        = tf_dfs["15m"]
            price        = df_15["close"].iloc[-1]
            ema50_15     = calc_ema50(df_15["close"])
            pct_diff     = (price - ema50_15) / ema50_15 * 100

            results_by_symbol[symbol] = {
                "symbol":        symbol,
                "price":         price,
                "ema50":         ema50_15,
                "pct_diff":      pct_diff,
                "rsi14":         tf_rsi["15m"],
                "tf_biases":     tf_biases,
                "consensus":     consensus,
                "volume_signal": vol_signal,
            }
            print(f"  {tf_biases}  consensus={consensus}  vol={vol_signal}")

        except Exception as e:
            print(f"  [ERR] {symbol}: {e}")
            errors.append(f"{symbol}: {e}")

    # ── Build snapshot ────────────────────────────────────────────────────────
    sep = "═" * 39
    lines = [sep, f"SNAPSHOT — {ts_label}", sep]

    total_counts = {}

    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        lines.append(f"\n═══ {cat} ═══")
        cat_counts = {}

        for sym in symbols:
            if sym not in results_by_symbol:
                lines.append(f"{sym}  HATA")
                continue
            r = results_by_symbol[sym]
            b = r["tf_biases"]
            lines.append(f"{sym}  {fmt_price(sym, r['price'])}")
            lines.append(
                f"  15m: {b['15m']:<8} 1h: {b['1h']:<8} 4h: {b['4h']:<8} → {r['consensus']}"
            )
            lines.append(f"  RSI {r['rsi14']:.1f} | Volume: {r['volume_signal']}")

            c = r["consensus"]
            cat_counts[c] = cat_counts.get(c, 0) + 1
            total_counts[c] = total_counts.get(c, 0) + 1

        # Category summary
        summary_parts = [f"{v} {k}" for k, v in sorted(cat_counts.items())]
        lines.append(f"→ {', '.join(summary_parts)}")

    lines += ["", sep]
    total_parts = [f"{v} {k}" for k, v in sorted(total_counts.items())]
    lines.append(f"Genel: {', '.join(total_parts)}")
    lines.append(sep)
    if errors:
        lines.append(f"HATALAR: {'; '.join(errors)}")

    snapshot_text = "\n".join(lines)
    print("\n" + snapshot_text + "\n")

    # ── Write decisions.jsonl ─────────────────────────────────────────────────
    print("[decisions.jsonl] Yazılıyor...")
    with open(DECISIONS_FILE, "a", encoding="utf-8") as f:
        for r in results_by_symbol.values():
            record = {
                "timestamp":     ts_str,
                "source":        "mainnet",
                "symbol":        r["symbol"],
                "timeframe":     "15m",
                "type":          "bias",
                "verdict":       r["tf_biases"]["15m"],
                "price":         round(r["price"], 6),
                "ema50":         round(r["ema50"], 6),
                "rsi14":         round(r["rsi14"], 2),
                "tf_biases":     r["tf_biases"],
                "consensus":     r["consensus"],
                "volume_signal": r["volume_signal"],
                "details": (
                    f"MTF snapshot. EMA50 {'üstünde' if r['pct_diff'] >= 0 else 'altında'} "
                    f"({r['pct_diff']:+.2f}%), RSI {r['rsi14']:.1f}, "
                    f"consensus={r['consensus']}, vol={r['volume_signal']}."
                ),
                "trade_plan": {"entry": None, "stop": None, "target": None, "rr": None},
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  [OK] {len(results_by_symbol)} kayıt eklendi.")

    # ── Telegram ──────────────────────────────────────────────────────────────
    print("[Telegram] Gönderiliyor...")
    if errors:
        telegram_send(f"SNAPSHOT HATASI ({ts_label}):\n" + "\n".join(errors))
        return

    tg_lines = [f"<b>SNAPSHOT — {ts_label}</b>"]
    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        tg_lines.append(f"\n<b>═══ {cat} ═══</b>")
        cat_counts = {}
        for sym in symbols:
            if sym not in results_by_symbol:
                tg_lines.append(f"{sym}  HATA")
                continue
            r = results_by_symbol[sym]
            b = r["tf_biases"]
            tg_lines.append(f"<b>{sym}</b>  {fmt_price(sym, r['price'])}")
            tg_lines.append(
                f"  15m:{b['15m'][:4]}  1h:{b['1h'][:4]}  4h:{b['4h'][:4]}  → {r['consensus']}"
            )
            tg_lines.append(f"  RSI {r['rsi14']:.1f} | {r['volume_signal']}")
            c = r["consensus"]
            cat_counts[c] = cat_counts.get(c, 0) + 1
        summary_parts = [f"{v} {k}" for k, v in sorted(cat_counts.items())]
        tg_lines.append(f"→ {', '.join(summary_parts)}")

    tg_lines += ["", f"<b>Genel: {', '.join(total_parts)}</b>"]
    telegram_send_long("\n".join(tg_lines))

    print("\n=== SNAPSHOT TAMAMLANDI ===")


if __name__ == "__main__":
    main()

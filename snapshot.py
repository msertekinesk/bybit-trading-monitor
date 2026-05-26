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

# Backward compat: düz liste
WATCHLIST = [coin for coins in WATCHLIST_BY_CATEGORY.values() for coin in coins]

DECISIONS_FILE = os.path.join(os.path.dirname(__file__), "decisions.jsonl")
TZ_LOCAL = timezone(timedelta(hours=3))  # UTC+3

# ── Bybit REST helpers (private endpoint altyapısı) ───────────────────────────
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
def get_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    print(f"  [API] {symbol} {interval} kline çekiliyor...")
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
    above_ema = price > ema50
    if above_ema and 45 <= rsi <= 70:
        return "bullish"
    if not above_ema and 30 <= rsi <= 55:
        return "bearish"
    return "neutral"


# ── Formatting helpers ────────────────────────────────────────────────────────
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


def coin_line(r: dict) -> str:
    sym      = r["symbol"]
    price_s  = fmt_price(sym, r["price"])
    sign     = "+" if r["pct_diff"] >= 0 else ""
    ema_s    = f"EMA {sign}{r['pct_diff']:.2f}%"
    rsi_s    = f"RSI {r['rsi14']:.1f}"
    bias_s   = r["bias"]
    return f"{sym:<12} {price_s:<12} {ema_s:<12} {rsi_s:<10} {bias_s}"


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
            print(f"  [ERR] Telegram hatası: {r.json()}")
    except Exception as e:
        print(f"  [ERR] Telegram isteği başarısız: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now      = datetime.now(TZ_LOCAL)
    ts_str   = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    ts_label = now.strftime("%Y-%m-%d %H:%M UTC+3")
    print(f"\n=== SNAPSHOT {ts_label} ===\n")

    # ── Fetch & calculate ─────────────────────────────────────────────────────
    results_by_symbol = {}
    errors = []

    for symbol in WATCHLIST:
        print(f"[{symbol}]")
        try:
            df      = get_klines(symbol, interval="15m", limit=200)
            closes  = df["close"]
            price   = closes.iloc[-1]
            ema50   = calc_ema50(closes)
            rsi14   = calc_rsi14(closes)
            bias    = evaluate_bias(price, ema50, rsi14)
            pct_diff = (price - ema50) / ema50 * 100
            results_by_symbol[symbol] = {
                "symbol": symbol, "price": price, "ema50": ema50,
                "rsi14": rsi14, "bias": bias, "pct_diff": pct_diff,
            }
            print(f"  price={price:.4f}  ema50={ema50:.4f}  rsi14={rsi14:.1f}  bias={bias}")
        except Exception as e:
            print(f"  [ERR] {symbol}: {e}")
            errors.append(f"{symbol}: {e}")

    # ── Build snapshot text ───────────────────────────────────────────────────
    sep = "═" * 39
    lines = [sep, f"SNAPSHOT — {ts_label}", sep]

    total_bull = total_bear = total_neu = 0

    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        lines.append(f"\n═══ {cat} ═══")
        cat_bull = cat_bear = cat_neu = 0
        for sym in symbols:
            if sym not in results_by_symbol:
                lines.append(f"{sym:<12} HATA")
                continue
            r = results_by_symbol[sym]
            lines.append(coin_line(r))
            if r["bias"] == "bullish":
                cat_bull += 1
            elif r["bias"] == "bearish":
                cat_bear += 1
            else:
                cat_neu += 1
        n = len([s for s in symbols if s in results_by_symbol])
        lines.append(f"→ {cat_bull}/{n} bullish, {cat_bear}/{n} bearish"
                     + (f", {cat_neu}/{n} neutral" if cat_neu else ""))
        total_bull += cat_bull
        total_bear += cat_bear
        total_neu  += cat_neu

    lines += [
        "",
        sep,
        f"Genel: {total_bull} bullish, {total_bear} bearish, {total_neu} neutral",
        sep,
    ]
    if errors:
        lines.append(f"HATALAR: {'; '.join(errors)}")

    snapshot_text = "\n".join(lines)
    print("\n" + snapshot_text + "\n")

    # ── Write decisions.jsonl ─────────────────────────────────────────────────
    print("[decisions.jsonl] Kayıtlar yazılıyor...")
    with open(DECISIONS_FILE, "a", encoding="utf-8") as f:
        for r in results_by_symbol.values():
            record = {
                "timestamp": ts_str,
                "source": "mainnet",
                "symbol": r["symbol"],
                "timeframe": "15m",
                "type": "bias",
                "verdict": r["bias"],
                "price": round(r["price"], 6),
                "ema50": round(r["ema50"], 6),
                "rsi14": round(r["rsi14"], 2),
                "details": (
                    f"GitHub Actions snapshot. EMA50 "
                    f"{'üstünde' if r['pct_diff'] >= 0 else 'altında'} "
                    f"({r['pct_diff']:+.2f}%), RSI {r['rsi14']:.1f}."
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
        cat_bull = cat_bear = cat_neu = 0
        for sym in symbols:
            if sym not in results_by_symbol:
                tg_lines.append(f"{sym} HATA")
                continue
            r = results_by_symbol[sym]
            tg_lines.append(coin_line(r))
            if r["bias"] == "bullish":   cat_bull += 1
            elif r["bias"] == "bearish": cat_bear += 1
            else:                        cat_neu  += 1
        n = len([s for s in symbols if s in results_by_symbol])
        tg_lines.append(f"→ {cat_bull}/{n} bullish, {cat_bear}/{n} bearish"
                        + (f", {cat_neu}/{n} neutral" if cat_neu else ""))

    tg_lines += [
        "",
        f"<b>Genel: {total_bull} bullish, {total_bear} bearish, {total_neu} neutral</b>",
    ]

    tg_msg = "\n".join(tg_lines)
    if len(tg_msg) > 4000:
        tg_msg = tg_msg[:3990] + "\n[mesaj kesildi]"
    telegram_send(tg_msg)

    print("\n=== SNAPSHOT TAMAMLANDI ===")


if __name__ == "__main__":
    main()

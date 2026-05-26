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

BASE_URL   = "https://api.bybit-tr.com"
WATCHLIST  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
DECISIONS_FILE = os.path.join(os.path.dirname(__file__), "decisions.jsonl")
TZ_LOCAL = timezone(timedelta(hours=3))  # UTC+3

# ── Bybit REST helpers ────────────────────────────────────────────────────────
def _sign(params: dict) -> dict:
    """Add HMAC-SHA256 signature for private endpoints."""
    ts = str(int(time.time() * 1000))
    recv_window = "5000"
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    raw = f"{ts}{BYBIT_API_KEY}{recv_window}{query}"
    sig = hmac.new(BYBIT_API_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    params.update({
        "api_key": BYBIT_API_KEY,
        "timestamp": ts,
        "recv_window": recv_window,
        "sign": sig,
    })
    return params


def get_klines(symbol: str, interval: str = "15", limit: int = 200) -> pd.DataFrame:
    """Fetch kline data from Bybit public API. Returns DataFrame with OHLCV."""
    url = f"{BASE_URL}/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
    print(f"  [API] {symbol} {interval}m kline çekiliyor...")
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data["retCode"] != 0:
        raise ValueError(f"Bybit API hatası: {data['retMsg']}")
    rows = data["result"]["list"]
    # rows: newest first → reverse for chronological order
    rows = list(reversed(rows))
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_numeric(df["ts"])
    return df


# ── Indicator calculations ────────────────────────────────────────────────────
def calc_ema50(closes: pd.Series) -> float:
    """EMA50: seed = first close, k = 2/51."""
    k = 2 / 51
    ema = closes.iloc[0]
    for price in closes.iloc[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def calc_rsi14(closes: pd.Series) -> float:
    """RSI(14) with Wilder's smoothing. Seed = SMA of first 14 gains/losses."""
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
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ── Bias evaluation ───────────────────────────────────────────────────────────
def evaluate_bias(price: float, ema50: float, rsi: float) -> str:
    above_ema = price > ema50
    if above_ema and 45 <= rsi <= 70:
        return "bullish"
    if not above_ema and 30 <= rsi <= 55:
        return "bearish"
    return "neutral"


# ── Telegram ──────────────────────────────────────────────────────────────────
def telegram_send(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [WARN] Telegram credentials eksik, mesaj gönderilmedi.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=payload, timeout=10)
        result = r.json()
        if result.get("ok"):
            print("  [OK] Telegram gönderildi.")
        else:
            print(f"  [ERR] Telegram hatası: {result}")
    except Exception as e:
        print(f"  [ERR] Telegram isteği başarısız: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(TZ_LOCAL)
    ts_str = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    ts_label = now.strftime("%Y-%m-%d %H:%M UTC+3")
    print(f"\n=== SNAPSHOT {ts_label} ===\n")

    results = []
    errors  = []

    for symbol in WATCHLIST:
        print(f"[{symbol}]")
        try:
            df = get_klines(symbol, interval="15", limit=200)
            closes  = df["close"]
            price   = closes.iloc[-1]
            ema50   = calc_ema50(closes)
            rsi14   = calc_rsi14(closes)
            bias    = evaluate_bias(price, ema50, rsi14)
            pct_diff = (price - ema50) / ema50 * 100
            direction = "üstünde" if price > ema50 else "altında"

            results.append({
                "symbol": symbol,
                "price": price,
                "ema50": ema50,
                "rsi14": rsi14,
                "bias": bias,
                "pct_diff": pct_diff,
                "direction": direction,
            })
            print(f"  price={price:.4f}  ema50={ema50:.4f}  rsi14={rsi14:.1f}  bias={bias}")

        except Exception as e:
            print(f"  [ERR] {symbol} işlenemedi: {e}")
            errors.append(f"{symbol}: {e}")

    # ── Build snapshot text ───────────────────────────────────────────────────
    sep = "═" * 39
    lines = [sep, f"SNAPSHOT — {ts_label}", sep, ""]

    price_fmts = {
        "BTCUSDT": lambda p: f"${p:,.2f}",
        "ETHUSDT": lambda p: f"${p:,.2f}",
        "SOLUSDT": lambda p: f"${p:.2f}",
        "BNBUSDT": lambda p: f"${p:.2f}",
        "XRPUSDT": lambda p: f"${p:.4f}",
    }
    ema_fmts = {
        "BTCUSDT": lambda p: f"${p:,.2f}",
        "ETHUSDT": lambda p: f"${p:,.2f}",
        "SOLUSDT": lambda p: f"${p:.2f}",
        "BNBUSDT": lambda p: f"${p:.2f}",
        "XRPUSDT": lambda p: f"${p:.4f}",
    }

    for r in results:
        sym = r["symbol"]
        pf  = price_fmts.get(sym, lambda p: f"${p:.4f}")
        ef  = ema_fmts.get(sym, lambda p: f"${p:.4f}")
        sign = "+" if r["pct_diff"] >= 0 else ""
        lines += [
            sym,
            f"  Fiyat:    {pf(r['price'])}",
            f"  EMA50:    {ef(r['ema50'])} (fiyat {r['direction']}, {sign}{r['pct_diff']:.2f}%)",
            f"  RSI(14):  {r['rsi14']:.1f}",
            f"  Bias:     {r['bias']}",
            "  Setup:    yok",
            "",
        ]

    if errors:
        lines.append(f"HATALAR: {'; '.join(errors)}")
        lines.append("")

    # Summary
    bullish_count = sum(1 for r in results if r["bias"] == "bullish")
    bearish_count = sum(1 for r in results if r["bias"] == "bearish")
    neutral_count = sum(1 for r in results if r["bias"] == "neutral")
    lines.append(
        f"Genel: {bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral"
    )
    lines.append(sep)

    snapshot_text = "\n".join(lines)
    print("\n" + snapshot_text + "\n")

    # ── Write decisions.jsonl ─────────────────────────────────────────────────
    print("[decisions.jsonl] Kayıtlar yazılıyor...")
    with open(DECISIONS_FILE, "a", encoding="utf-8") as f:
        for r in results:
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
                    f"GitHub Actions snapshot. "
                    f"EMA50 {'üstünde' if r['pct_diff'] >= 0 else 'altında'} "
                    f"({r['pct_diff']:+.2f}%), RSI {r['rsi14']:.1f}."
                ),
                "trade_plan": {"entry": None, "stop": None, "target": None, "rr": None},
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  [OK] {len(results)} kayıt eklendi.")

    # ── Telegram HTML message ─────────────────────────────────────────────────
    print("[Telegram] Gönderiliyor...")
    tg_lines = [f"<b>SNAPSHOT — {ts_label}</b>", ""]
    for r in results:
        sym = r["symbol"]
        pf  = price_fmts.get(sym, lambda p: f"${p:.4f}")
        ef  = ema_fmts.get(sym, lambda p: f"${p:.4f}")
        sign = "+" if r["pct_diff"] >= 0 else ""
        tg_lines += [
            f"<b>{sym}</b>",
            f"  Fiyat:   {pf(r['price'])}",
            f"  EMA50:   {ef(r['ema50'])} ({r['direction']}, {sign}{r['pct_diff']:.2f}%)",
            f"  RSI(14): {r['rsi14']:.1f}",
            f"  Bias:    {r['bias']}",
            f"  Setup:   yok",
            "",
        ]
    tg_lines.append(
        f"Genel: {bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral"
    )
    if errors:
        tg_lines.append(f"\nHATALAR: {'; '.join(errors)}")

    tg_msg = "\n".join(tg_lines)
    if len(tg_msg) > 4000:
        tg_msg = tg_msg[:3990] + "\n[mesaj kesildi]"

    if errors:
        telegram_send(f"SNAPSHOT HATASI ({ts_label}):\n" + "\n".join(errors))
    else:
        telegram_send(tg_msg)

    print("\n=== SNAPSHOT TAMAMLANDI ===")


if __name__ == "__main__":
    main()

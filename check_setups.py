#!/usr/bin/env python3
import os
import json
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

BASE_URL    = "https://data-api.binance.vision"
SETUPS_FILE = os.path.join(os.path.dirname(__file__), "setups.jsonl")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def get_klines_since(symbol, since_ms, interval="15m", limit=200):
    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "startTime": since_ms, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    rows = resp.json()
    df = pd.DataFrame(rows, columns=[
        "ts", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore"
    ])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_numeric(df["ts"])
    return df


def current_price(symbol):
    resp = requests.get(f"{BASE_URL}/api/v3/ticker/price", params={"symbol": symbol}, timeout=10)
    resp.raise_for_status()
    return float(resp.json()["price"])


def telegram_send(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    except Exception:
        pass


def resolve_setup(setup):
    direction = setup["direction"]
    entry     = setup["entry"]
    stop      = setup["stop"]
    target    = setup["target"]

    ts_open    = datetime.fromisoformat(setup["timestamp"])
    ts_open_ms = int(ts_open.astimezone(timezone.utc).timestamp() * 1000)
    now        = datetime.now(timezone.utc)
    elapsed_m  = (now - ts_open.astimezone(timezone.utc)).total_seconds() / 60

    try:
        df = get_klines_since(setup["symbol"], ts_open_ms)
    except Exception as e:
        print(f"  [ERR] kline alınamadı: {e}")
        return None

    result = result_price = result_ts = None

    for _, row in df.iterrows():
        candle_ts = datetime.fromtimestamp(row["ts"] / 1000, tz=timezone.utc)
        if direction == "LONG":
            if row["low"] <= stop:
                result, result_price, result_ts = "loss", stop, candle_ts
                break
            if row["high"] >= target:
                result, result_price, result_ts = "win", target, candle_ts
                break
        else:  # SHORT
            if row["high"] >= stop:
                result, result_price, result_ts = "loss", stop, candle_ts
                break
            if row["low"] <= target:
                result, result_price, result_ts = "win", target, candle_ts
                break

    if result is None:
        if elapsed_m < 1440:
            return None  # still active
        result = "timeout"
        try:
            result_price = current_price(setup["symbol"])
        except Exception:
            result_price = df["close"].iloc[-1] if len(df) > 0 else entry
        result_ts = now

    duration_m = int((result_ts - ts_open.astimezone(timezone.utc)).total_seconds() / 60)

    if direction == "LONG":
        risk = entry - stop
        actual_rr = round((result_price - entry) / risk, 2) if risk != 0 else 0
    else:
        risk = stop - entry
        actual_rr = round((entry - result_price) / risk, 2) if risk != 0 else 0

    resolved = setup.copy()
    resolved.update({
        "status":            result,
        "result":            result,
        "result_price":      round(result_price, 6),
        "result_timestamp":  result_ts.isoformat(),
        "duration_minutes":  duration_m,
        "actual_rr":         actual_rr,
    })
    return resolved


def main():
    if not os.path.exists(SETUPS_FILE):
        print("setups.jsonl bulunamadı, atlanıyor.")
        return

    with open(SETUPS_FILE, "r", encoding="utf-8") as f:
        setups = [json.loads(l) for l in f if l.strip()]

    active = [s for s in setups if s.get("status") == "active"]
    print(f"\n=== CHECK SETUPS ({len(active)} aktif) ===\n")

    if not active:
        print("Aktif setup yok.")
        return

    updated = False
    notifications = []
    idx_map = {s["setup_id"]: i for i, s in enumerate(setups)}

    for setup in active:
        sym = setup["symbol"]
        print(f"[{sym}] {setup['direction']} | entry {setup['entry']} | stop {setup['stop']} | target {setup['target']}")
        resolved = resolve_setup(setup)
        if resolved is None:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(setup["timestamp"]).astimezone(timezone.utc)).total_seconds() / 60
            print(f"  → Aktif  ({elapsed:.0f}dk geçti)")
            continue

        i = idx_map[setup["setup_id"]]
        setups[i] = resolved
        updated = True

        result   = resolved["result"]
        actual   = resolved["actual_rr"]
        dur_h    = resolved["duration_minutes"] // 60
        dur_m    = resolved["duration_minutes"] % 60
        print(f"  → {result.upper()} | R:R {actual:+.2f} | süre {dur_h}s{dur_m}dk")

        notifications.append(
            f"SETUP KAPANDI: {sym} {setup['direction']}\n"
            f"Sonuç: {result.upper()} ({actual:+.2f}R)\n"
            f"Süre: {dur_h}s {dur_m}dk | Fiyat: {resolved['result_price']}"
        )

    if updated:
        with open(SETUPS_FILE, "w", encoding="utf-8") as f:
            for s in setups:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"\n[OK] setups.jsonl güncellendi.")
        for msg in notifications:
            telegram_send(msg)
    else:
        print("Değişiklik yok.")

    print("\n=== CHECK SETUPS TAMAMLANDI ===")


if __name__ == "__main__":
    main()

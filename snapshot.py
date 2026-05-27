#!/usr/bin/env python3
import os
import json
import time
import hmac
import hashlib
import subprocess
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

WATCHLIST  = [coin for coins in WATCHLIST_BY_CATEGORY.values() for coin in coins]
TIMEFRAMES = ["15m", "1h", "4h"]

DECISIONS_FILE = os.path.join(os.path.dirname(__file__), "decisions.jsonl")
SETUPS_FILE    = os.path.join(os.path.dirname(__file__), "setups.jsonl")
TZ_LOCAL = timezone(timedelta(hours=3))

SETUP_EMOJI = {
    "STRONG_TREND": "🔥",
    "WEAK_TREND":   "⚡",
    "REVERSAL":     "🔄",
    "BREAKOUT":     "🚀",
}

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
    if bull == 3:  return "STRONG BULLISH"
    if bear == 3:  return "STRONG BEARISH"
    if bull == 2:  return "BULLISH"
    if bear == 2:  return "BEARISH"
    return "MIXED"


def volume_signal(df: pd.DataFrame) -> str:
    last_vol = df["volume"].iloc[-1]
    avg_20   = df["volume"].iloc[-21:-1].mean()
    ratio    = last_vol / avg_20 if avg_20 > 0 else 0
    if ratio >= 1.5:  return "HIGH VOL"
    if ratio <= 0.5:  return "LOW VOL"
    return "NORMAL VOL"


# ── Volume Profile ────────────────────────────────────────────────────────────
def calculate_volume_profile(df, num_bins=40):
    price_min = float(df["low"].min())
    price_max = float(df["high"].max())
    if price_max <= price_min:
        return {"poc": price_min, "val": price_min, "vah": price_max}
    bin_size = (price_max - price_min) / num_bins
    bins = [0.0] * num_bins
    for _, row in df.iterrows():
        lo = max(0, min(num_bins - 1, int((row["low"]  - price_min) / bin_size)))
        hi = max(0, min(num_bins - 1, int((row["high"] - price_min) / bin_size)))
        n = hi - lo + 1
        vol_each = row["volume"] / n
        for i in range(lo, hi + 1):
            bins[i] += vol_each
    poc_idx   = max(range(num_bins), key=lambda i: bins[i])
    poc_price = price_min + (poc_idx + 0.5) * bin_size
    total_vol = sum(bins)
    target    = total_vol * 0.70
    accumulated = bins[poc_idx]
    lo_ext = hi_ext = poc_idx
    while accumulated < target and (lo_ext > 0 or hi_ext < num_bins - 1):
        up = bins[hi_ext + 1] if hi_ext + 1 < num_bins else 0
        dn = bins[lo_ext - 1] if lo_ext - 1 >= 0 else 0
        if up >= dn and hi_ext + 1 < num_bins:
            hi_ext += 1; accumulated += up
        elif lo_ext - 1 >= 0:
            lo_ext -= 1; accumulated += dn
        else:
            break
    return {
        "poc": round(poc_price, 6),
        "val": round(price_min + lo_ext * bin_size, 6),
        "vah": round(price_min + (hi_ext + 1) * bin_size, 6),
    }


# ── Liquidity Sweep ───────────────────────────────────────────────────────────
def detect_liquidity_sweep(df, lookback=20):
    if len(df) < lookback + 3:
        return {"detected": False}
    recent   = df.iloc[-(lookback + 3):-3]
    swing_hi = float(recent["high"].max())
    swing_lo = float(recent["low"].min())
    last_3   = df.iloc[-3:]
    avg_vol  = float(df["volume"].iloc[-23:-3].mean()) if len(df) >= 23 else float(df["volume"].mean())
    if avg_vol == 0:
        return {"detected": False}
    for _, row in last_3.iterrows():
        hi, lo, cl, vol = float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"])
        span = hi - lo
        if span <= 0:
            continue
        if lo < swing_lo and cl > swing_lo and vol >= avg_vol * 1.3:
            rej = (cl - lo) / span
            if rej > 0.5:
                return {"detected": True, "type": "bullish_sweep",
                        "sweep_level": round(swing_lo, 6), "rejection_strength": round(rej, 2)}
        if hi > swing_hi and cl < swing_hi and vol >= avg_vol * 1.3:
            rej = (hi - cl) / span
            if rej > 0.5:
                return {"detected": True, "type": "bearish_sweep",
                        "sweep_level": round(swing_hi, 6), "rejection_strength": round(rej, 2)}
    return {"detected": False}


# ── Setup Helpers ─────────────────────────────────────────────────────────────
def compute_rr(entry, stop, target, direction):
    if direction == "LONG":
        risk   = entry - stop
        reward = target - entry
    else:
        risk   = stop - entry
        reward = entry - target
    if risk <= 0 or reward <= 0:
        return 0.0
    return reward / risk


def build_setup_dict(type_, direction, entry, stop, target, rr,
                     tf_biases, volume_signal_str, reasons, confidence):
    risk_pct   = abs(entry - stop) / entry * 100
    reward_pct = abs(target - entry) / entry * 100
    pos_dollars = round(10.0 / (risk_pct / 100), 2) if risk_pct > 0 else 0
    pos_coins   = round(pos_dollars / entry, 6) if entry > 0 else 0
    inv_dir = "altına" if direction == "LONG" else "üstüne"
    return {
        "type":                  type_,
        "direction":             direction,
        "entry":                 round(entry, 6),
        "stop":                  round(stop, 6),
        "target":                round(target, 6),
        "rr":                    round(rr, 2),
        "risk_pct":              round(risk_pct, 4),
        "reward_pct":            round(reward_pct, 4),
        "position_size_dollars": pos_dollars,
        "position_size_coins":   pos_coins,
        "tf_biases":             tf_biases,
        "volume_signal":         volume_signal_str,
        "trigger_reasons":       reasons,
        "confidence":            confidence,
        "invalidation":          f"Fiyat {round(stop, 6)} {inv_dir} 4H kapanış",
    }


# ── Setup Detection ───────────────────────────────────────────────────────────
def detect_strong_trend_setup(symbol, price, tf_biases, consensus,
                               volume_signal_str, klines_15m, liquidity_sweep):
    if consensus not in ("STRONG BULLISH", "STRONG BEARISH"):
        return None
    if volume_signal_str == "LOW VOL":
        return None

    last_20_low  = float(klines_15m["low"].iloc[-20:].min())
    last_20_high = float(klines_15m["high"].iloc[-20:].max())

    if consensus == "STRONG BULLISH":
        direction = "LONG"
        entry  = price
        stop   = last_20_low * 0.998
        target = float(klines_15m["high"].iloc[-50:].quantile(0.75))
    else:
        direction = "SHORT"
        entry  = price
        stop   = last_20_high * 1.002
        target = float(klines_15m["low"].iloc[-50:].quantile(0.25))

    rr = compute_rr(entry, stop, target, direction)
    if rr < 1.5:
        return None

    reasons = [f"3/3 {consensus}", f"Volume {volume_signal_str}"]
    expected_sweep = "bullish_sweep" if direction == "LONG" else "bearish_sweep"
    if liquidity_sweep.get("detected") and liquidity_sweep.get("type") == expected_sweep:
        reasons.append(f"Liquidity sweep ({liquidity_sweep['type']})")

    return build_setup_dict(
        type_="STRONG_TREND", direction=direction,
        entry=entry, stop=stop, target=target, rr=rr,
        tf_biases=tf_biases, volume_signal_str=volume_signal_str,
        reasons=reasons, confidence="HIGH",
    )


def detect_weak_trend_setup(symbol, price, tf_biases, consensus,
                             volume_signal_str, klines_15m, liquidity_sweep):
    if consensus not in ("BULLISH", "BEARISH"):
        return None
    if volume_signal_str == "LOW VOL":
        return None

    last_15_low  = float(klines_15m["low"].iloc[-15:].min())
    last_15_high = float(klines_15m["high"].iloc[-15:].max())

    if consensus == "BULLISH":
        direction = "LONG"
        entry  = price
        stop   = last_15_low * 0.997
        target = float(klines_15m["high"].iloc[-40:].quantile(0.70))
    else:
        direction = "SHORT"
        entry  = price
        stop   = last_15_high * 1.003
        target = float(klines_15m["low"].iloc[-40:].quantile(0.30))

    rr = compute_rr(entry, stop, target, direction)
    if rr < 1.3:
        return None

    same_dir = [tf for tf, bias in tf_biases.items()
                if bias == ("bullish" if direction == "LONG" else "bearish")]
    reasons = [
        f"2/3 {consensus} ({', '.join(same_dir)} aligned)",
        f"Volume {volume_signal_str}",
    ]
    return build_setup_dict(
        type_="WEAK_TREND", direction=direction,
        entry=entry, stop=stop, target=target, rr=rr,
        tf_biases=tf_biases, volume_signal_str=volume_signal_str,
        reasons=reasons, confidence="MEDIUM",
    )


def detect_reversal_setup(symbol, price, rsi, tf_biases,
                           volume_signal_str, klines_15m, liquidity_sweep):
    if volume_signal_str == "LOW VOL":
        return None
    if not liquidity_sweep.get("detected"):
        return None

    sweep_type = liquidity_sweep.get("type")
    rejection  = liquidity_sweep.get("rejection_strength", 0)
    if rejection < 0.6:
        return None

    last_20_low  = float(klines_15m["low"].iloc[-20:].min())
    last_20_high = float(klines_15m["high"].iloc[-20:].max())
    range_size   = last_20_high - last_20_low

    if rsi <= 35 and sweep_type == "bullish_sweep":
        direction = "LONG"
        entry     = price
        stop      = liquidity_sweep["sweep_level"] * 0.997
        target    = (last_20_low + last_20_high) / 2 + range_size * 0.3
        rsi_label = "oversold"
    elif rsi >= 65 and sweep_type == "bearish_sweep":
        direction = "SHORT"
        entry     = price
        stop      = liquidity_sweep["sweep_level"] * 1.003
        target    = (last_20_low + last_20_high) / 2 - range_size * 0.3
        rsi_label = "overbought"
    else:
        return None

    rr = compute_rr(entry, stop, target, direction)
    if rr < 1.5:
        return None

    reasons = [
        f"RSI {rsi:.1f} ({rsi_label})",
        f"Liquidity sweep ({sweep_type})",
        f"Rejection strength {rejection:.0%}",
        f"Volume {volume_signal_str}",
    ]
    return build_setup_dict(
        type_="REVERSAL", direction=direction,
        entry=entry, stop=stop, target=target, rr=rr,
        tf_biases=tf_biases, volume_signal_str=volume_signal_str,
        reasons=reasons, confidence="MEDIUM",
    )


def detect_pullback_setup(symbol, price, tf_biases, volume_signal_str, klines_15m, klines_4h):
    if volume_signal_str == "LOW VOL":
        return None

    bias_4h  = tf_biases.get("4h", "neutral")
    bias_1h  = tf_biases.get("1h", "neutral")
    bias_15m = tf_biases.get("15m", "neutral")

    if bias_4h not in ("bullish", "bearish"):
        return None
    if bias_4h != bias_1h:
        return None
    if bias_15m == bias_4h:
        return None

    main_trend   = bias_4h
    last_20_low  = float(klines_15m["low"].iloc[-20:].min())
    last_20_high = float(klines_15m["high"].iloc[-20:].max())
    last_50_high = float(klines_15m["high"].iloc[-50:].max())
    last_50_low  = float(klines_15m["low"].iloc[-50:].min())

    if main_trend == "bullish":
        if price > last_20_low * 1.015:
            return None
        direction = "LONG"
        entry  = price
        stop   = last_20_low * 0.997
        target = last_50_high
        tf_label = "düzeltme"
    else:
        if price < last_20_high * 0.985:
            return None
        direction = "SHORT"
        entry  = price
        stop   = last_20_high * 1.003
        target = last_50_low
        tf_label = "bounce"

    rr = compute_rr(entry, stop, target, direction)
    if rr < 1.5:
        return None

    reasons = [
        f"4H/1H {main_trend} (ana trend)",
        f"15m {tf_label}",
        f"Volume {volume_signal_str}",
    ]
    return build_setup_dict(
        type_="PULLBACK", direction=direction,
        entry=entry, stop=stop, target=target, rr=rr,
        tf_biases=tf_biases, volume_signal_str=volume_signal_str,
        reasons=reasons, confidence="MEDIUM",
    )


def detect_breakout_setup(symbol, price, tf_biases, volume_signal_str, klines_15m):
    if volume_signal_str != "HIGH VOL":
        return None
    if len(klines_15m) < 22:
        return None

    last_20      = klines_15m.iloc[-21:-1]
    last_20_high = float(last_20["high"].max())
    last_20_low  = float(last_20["low"].min())
    if last_20_low <= 0:
        return None
    range_size = (last_20_high - last_20_low) / last_20_low

    if range_size > 0.025:
        return None

    lc = klines_15m.iloc[-1]
    lc_open  = float(lc["open"])
    lc_close = float(lc["close"])

    if lc_close > last_20_high and lc_close > lc_open:
        direction = "LONG"
        entry  = price
        stop   = last_20_low * 0.997
        target = last_20_high + (last_20_high - last_20_low)
    elif lc_close < last_20_low and lc_close < lc_open:
        direction = "SHORT"
        entry  = price
        stop   = last_20_high * 1.003
        target = last_20_low - (last_20_high - last_20_low)
    else:
        return None

    rr = compute_rr(entry, stop, target, direction)
    if rr < 1.5:
        return None

    reasons = [
        f"Konsolidasyon ({range_size:.1%} range)",
        f"Range kırılımı ({'yukarı' if direction == 'LONG' else 'aşağı'})",
        "Volume HIGH (spike)",
    ]
    return build_setup_dict(
        type_="BREAKOUT", direction=direction,
        entry=entry, stop=stop, target=target, rr=rr,
        tf_biases=tf_biases, volume_signal_str=volume_signal_str,
        reasons=reasons, confidence="HIGH",
    )


def detect_all_setups(symbol, price, rsi, tf_biases, consensus,
                      volume_signal_str, klines_15m, klines_4h, liquidity_sweep):
    """Priority: STRONG_TREND > BREAKOUT > REVERSAL > PULLBACK > WEAK_TREND"""
    for fn in [
        lambda: detect_strong_trend_setup(symbol, price, tf_biases, consensus, volume_signal_str, klines_15m, liquidity_sweep),
        lambda: detect_breakout_setup(symbol, price, tf_biases, volume_signal_str, klines_15m),
        lambda: detect_reversal_setup(symbol, price, rsi, tf_biases, volume_signal_str, klines_15m, liquidity_sweep),
        lambda: detect_pullback_setup(symbol, price, tf_biases, volume_signal_str, klines_15m, klines_4h),
        lambda: detect_weak_trend_setup(symbol, price, tf_biases, consensus, volume_signal_str, klines_15m, liquidity_sweep),
    ]:
        result = fn()
        if result:
            return result
    return None


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


def _setup_emoji(s: dict) -> str:
    t = s.get("type", "STRONG_TREND")
    if t == "PULLBACK":
        return "📉" if s["direction"] == "LONG" else "📈"
    return SETUP_EMOJI.get(t, "")


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


def format_setup_block(sym: str, s: dict) -> str:
    entry = s["entry"]; stop = s["stop"]; target = s["target"]; rr = s["rr"]
    risk_a = abs(entry - stop)
    rew_a  = abs(target - entry)
    risk_p = s.get("risk_pct",  (risk_a / entry) * 100)
    rew_p  = s.get("reward_pct", (rew_a / entry) * 100)
    pos_d  = s.get("position_size_dollars", round(10 / (risk_p / 100), 2))
    pos_c  = s.get("position_size_coins",   round(pos_d / entry, 6))
    rew_d  = round(pos_d * (rew_p / 100), 2)
    coin_lbl   = sym.replace("USDT", "")
    inv_dir    = "üstüne" if s["direction"] == "SHORT" else "altına"
    setup_type = s.get("type", "STRONG_TREND")
    emoji      = _setup_emoji(s)
    confidence = s.get("confidence", "HIGH")

    rows = [
        f"🚨 SETUP: <b>{sym} {s['direction']}</b> [{setup_type}] {emoji}",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"Entry:   <code>{fmt_price(sym, entry)}</code>",
        f"Stop:    <code>{fmt_price(sym, stop)}</code>  (risk: {fmt_price(sym, risk_a)}, %{risk_p:.2f})",
        f"Target:  <code>{fmt_price(sym, target)}</code>  (kazanç: {fmt_price(sym, rew_a)}, %{rew_p:.2f})",
        f"R:R:     <b>{rr}:1</b>",
        "",
        "Pozisyon (%1 risk @ $1000):",
        f"  Size:   ${pos_d:,.0f} (≈ {pos_c:.4g} {coin_lbl})",
        f"  Risk:   $10.00",
        f"  Reward: ${rew_d:.2f}",
        "",
        f"Confidence: {confidence}",
    ]
    reasons = s.get("trigger_reasons", [])
    if reasons:
        rows += ["", "Tetikleyici:"] + [f"  • {r}" for r in reasons]
    rows += ["", "İptal koşulu:", f"  Fiyat {fmt_price(sym, stop)} {inv_dir} 4H kapanış"]
    return "\n".join(rows)


def telegram_send_long(text: str) -> None:
    if len(text) <= 4096:
        telegram_send(text)
        return
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
                df     = get_klines(symbol, interval=tf, limit=200)
                closes = df["close"]
                price  = float(closes.iloc[-1])
                ema50  = calc_ema50(closes)
                rsi14  = calc_rsi14(closes)
                bias   = evaluate_bias(price, ema50, rsi14)
                tf_dfs[tf]    = df
                tf_biases[tf] = bias
                tf_rsi[tf]    = rsi14

            consensus      = consensus_bias(tf_biases)
            vol_signal_str = volume_signal(tf_dfs["15m"])
            df_15          = tf_dfs["15m"]
            price          = float(df_15["close"].iloc[-1])
            ema50_15       = calc_ema50(df_15["close"])
            pct_diff       = (price - ema50_15) / ema50_15 * 100

            vol_profile = calculate_volume_profile(df_15)
            liq_sweep   = detect_liquidity_sweep(df_15)

            setup = detect_all_setups(
                symbol=symbol,
                price=price,
                rsi=tf_rsi["15m"],
                tf_biases=tf_biases,
                consensus=consensus,
                volume_signal_str=vol_signal_str,
                klines_15m=df_15,
                klines_4h=tf_dfs["4h"],
                liquidity_sweep=liq_sweep,
            )

            results_by_symbol[symbol] = {
                "symbol":          symbol,
                "price":           price,
                "ema50":           ema50_15,
                "pct_diff":        pct_diff,
                "rsi14":           tf_rsi["15m"],
                "tf_biases":       tf_biases,
                "consensus":       consensus,
                "volume_signal":   vol_signal_str,
                "setup":           setup,
                "volume_profile":  vol_profile,
                "liquidity_sweep": liq_sweep,
            }
            sweep_tag = "  SWEEP" if liq_sweep.get("detected") else ""
            setup_tag = f"  SETUP={setup['direction']}[{setup['type']}]" if setup else ""
            print(f"  {tf_biases}  consensus={consensus}  vol={vol_signal_str}{setup_tag}{sweep_tag}")

        except Exception as e:
            print(f"  [ERR] {symbol}: {e}")
            errors.append(f"{symbol}: {e}")

    # ── Build snapshot text ───────────────────────────────────────────────────
    sep = "═" * 39
    lines = [sep, f"SNAPSHOT — {ts_label}", sep]

    total_counts = {}
    all_setups   = []

    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        lines.append(f"\n═══ {cat} ═══")
        cat_counts    = {}
        cat_setup_cnt = 0

        for sym in symbols:
            if sym not in results_by_symbol:
                lines.append(f"{sym}  HATA")
                continue
            r = results_by_symbol[sym]
            b = r["tf_biases"]
            lines.append(f"{sym}  {fmt_price(sym, r['price'])}")
            lines.append(f"  15m: {b['15m']:<8} 1h: {b['1h']:<8} 4h: {b['4h']:<8} → {r['consensus']}")
            lines.append(f"  RSI {r['rsi14']:.1f} | Volume: {r['volume_signal']}")
            vp = r.get("volume_profile", {})
            if vp:
                lines.append(f"  POC: {fmt_price(sym, vp['poc'])} | VA: {fmt_price(sym, vp['val'])} - {fmt_price(sym, vp['vah'])}")
            ls = r.get("liquidity_sweep", {})
            if ls.get("detected"):
                sw_lbl = "bullish" if ls["type"] == "bullish_sweep" else "bearish"
                lines.append(f"  SWEEP: {sw_lbl} @ {fmt_price(sym, ls['sweep_level'])} (rej {ls['rejection_strength']:.0%})")
            if r["setup"]:
                s = r["setup"]
                st = s.get("type", "STRONG_TREND")
                lines.append(
                    f"  ↪ {s['direction']} SETUP [{st}]: entry {fmt_price(sym, s['entry'])} | "
                    f"stop {fmt_price(sym, s['stop'])} | target {fmt_price(sym, s['target'])} | "
                    f"R:R {s['rr']}:1"
                )
                cat_setup_cnt += 1
                all_setups.append((sym, r["setup"]))

            c = r["consensus"]
            cat_counts[c]   = cat_counts.get(c, 0) + 1
            total_counts[c] = total_counts.get(c, 0) + 1

        summary_parts = [f"{v} {k}" for k, v in sorted(cat_counts.items())]
        setup_sfx = f" | {cat_setup_cnt} SETUP" if cat_setup_cnt else ""
        lines.append(f"→ {', '.join(summary_parts)}{setup_sfx}")

    lines += ["", sep]
    total_parts       = [f"{v} {k}" for k, v in sorted(total_counts.items())]
    total_setup_count = len(all_setups)
    lines.append(f"Genel: {', '.join(total_parts)}{f' | {total_setup_count} SETUP' if total_setup_count else ''}")
    lines.append(sep)

    if all_setups:
        lines.append(f"\n═══ AKTİF SETUPLAR ({total_setup_count}) ═══")
        for sym, s in all_setups:
            st = s.get("type", "STRONG_TREND")
            lines.append(
                f"{sym} {s['direction']} [{st}]  entry {fmt_price(sym, s['entry'])}  "
                f"R:R {s['rr']}:1  ({s.get('confidence', '?')})"
            )
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
                "timestamp":       ts_str,
                "source":          "mainnet",
                "symbol":          r["symbol"],
                "timeframe":       "15m",
                "type":            "bias",
                "verdict":         r["tf_biases"]["15m"],
                "price":           round(r["price"], 6),
                "ema50":           round(r["ema50"], 6),
                "rsi14":           round(r["rsi14"], 2),
                "tf_biases":       r["tf_biases"],
                "consensus":       r["consensus"],
                "volume_signal":   r["volume_signal"],
                "details": (
                    f"MTF snapshot. EMA50 {'üstünde' if r['pct_diff'] >= 0 else 'altında'} "
                    f"({r['pct_diff']:+.2f}%), RSI {r['rsi14']:.1f}, "
                    f"consensus={r['consensus']}, vol={r['volume_signal']}."
                ),
                "setup":           r["setup"],
                "volume_profile":  r.get("volume_profile"),
                "liquidity_sweep": r.get("liquidity_sweep"),
                "trade_plan":      {"entry": None, "stop": None, "target": None, "rr": None},
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  [OK] {len(results_by_symbol)} kayıt eklendi.")

    # ── Write setups.jsonl ────────────────────────────────────────────────────
    if all_setups:
        print("[setups.jsonl] Kontrol ediliyor...")
        existing_active = set()
        if os.path.exists(SETUPS_FILE):
            with open(SETUPS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("status") == "active":
                            existing_active.add((rec["symbol"], rec["direction"]))
                    except Exception:
                        pass
        ts_utc    = now.astimezone(timezone.utc)
        new_count = 0
        with open(SETUPS_FILE, "a", encoding="utf-8") as f:
            for sym, s in all_setups:
                if (sym, s["direction"]) in existing_active:
                    continue
                setup_id = f"{sym}-{ts_utc.strftime('%Y%m%dT%H%M%SZ')}-{s['direction']}"
                record = {
                    "setup_id":              setup_id,
                    "timestamp":             ts_str,
                    "symbol":                sym,
                    "direction":             s["direction"],
                    "type":                  s.get("type", "STRONG_TREND"),
                    "confidence":            s.get("confidence", "HIGH"),
                    "entry":                 s["entry"],
                    "stop":                  s["stop"],
                    "target":                s["target"],
                    "rr_planned":            s["rr"],
                    "risk_pct":              s.get("risk_pct"),
                    "reward_pct":            s.get("reward_pct"),
                    "position_size_dollars": s.get("position_size_dollars"),
                    "position_size_coins":   s.get("position_size_coins"),
                    "trigger_reasons":       s.get("trigger_reasons", []),
                    "invalidation":          s.get("invalidation", ""),
                    "tf_biases":             results_by_symbol[sym]["tf_biases"],
                    "volume_signal":         results_by_symbol[sym]["volume_signal"],
                    "status":                "active",
                    "result":                None,
                    "result_price":          None,
                    "result_timestamp":      None,
                    "duration_minutes":      None,
                    "actual_rr":             None,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                new_count += 1
        skipped = len(all_setups) - new_count
        print(f"  [OK] {new_count} yeni setup eklendi ({skipped} zaten aktif).")

    # ── Telegram ──────────────────────────────────────────────────────────────
    print("[Telegram] Gönderiliyor...")
    if errors:
        telegram_send(f"SNAPSHOT HATASI ({ts_label}):\n" + "\n".join(errors))
        return

    tg_lines = [f"<b>SNAPSHOT — {ts_label}</b>"]
    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        tg_lines.append(f"\n<b>═══ {cat} ═══</b>")
        cat_counts     = {}
        cat_setup_cnt_tg = 0
        for sym in symbols:
            if sym not in results_by_symbol:
                tg_lines.append(f"{sym}  HATA")
                continue
            r = results_by_symbol[sym]
            b = r["tf_biases"]
            tg_lines.append(f"<b>{sym}</b>  {fmt_price(sym, r['price'])}")
            tg_lines.append(f"  15m:{b['15m'][:4]}  1h:{b['1h'][:4]}  4h:{b['4h'][:4]}  → {r['consensus']}")
            tg_lines.append(f"  RSI {r['rsi14']:.1f} | {r['volume_signal']}")
            vp = r.get("volume_profile", {})
            if vp:
                tg_lines.append(
                    f"  POC: <code>{fmt_price(sym, vp['poc'])}</code> | VA: {fmt_price(sym, vp['val'])} - {fmt_price(sym, vp['vah'])}"
                )
            ls = r.get("liquidity_sweep", {})
            if ls and ls.get("detected"):
                sw_lbl = "bullish" if ls["type"] == "bullish_sweep" else "bearish"
                tg_lines.append(f"  SWEEP: {sw_lbl} @ {fmt_price(sym, ls['sweep_level'])}")
            if r["setup"]:
                s  = r["setup"]
                st = s.get("type", "STRONG_TREND")
                em = _setup_emoji(s)
                tg_lines.append(
                    f"  ↪ {s['direction']} SETUP [{st}] {em}: entry {fmt_price(sym, s['entry'])} | "
                    f"stop {fmt_price(sym, s['stop'])} | target {fmt_price(sym, s['target'])} | "
                    f"R:R {s['rr']}:1"
                )
                cat_setup_cnt_tg += 1
            c = r["consensus"]
            cat_counts[c] = cat_counts.get(c, 0) + 1
        summary_parts = [f"{v} {k}" for k, v in sorted(cat_counts.items())]
        setup_sfx_tg = f" | {cat_setup_cnt_tg} SETUP" if cat_setup_cnt_tg else ""
        tg_lines.append(f"→ {', '.join(summary_parts)}{setup_sfx_tg}")

    setup_total_sfx_tg = f" | {total_setup_count} SETUP" if total_setup_count else ""
    tg_lines += ["", f"<b>Genel: {', '.join(total_parts)}{setup_total_sfx_tg}</b>"]
    snapshot_msg = "\n".join(tg_lines)

    if all_setups:
        sorted_setups = sorted(all_setups, key=lambda x: x[1]["rr"], reverse=True)
        blocks = [format_setup_block(sym, s) for sym, s in sorted_setups]
        full_msg = snapshot_msg + "\n\n" + "\n\n".join(blocks)
        if len(full_msg) <= 4000:
            telegram_send_long(full_msg)
        else:
            telegram_send_long(snapshot_msg)
            top3 = blocks[:3]
            rest = sorted_setups[3:]
            detail_msg = "\n\n".join(top3)
            if rest:
                short = ", ".join(
                    f"{sym} {s['direction']} [{s.get('type','')}] (R:R {s['rr']})"
                    for sym, s in rest
                )
                detail_msg += f"\n\nAyrıca: {short}"
            telegram_send_long(detail_msg)
    else:
        telegram_send_long(snapshot_msg)

    # ── Build dashboard ───────────────────────────────────────────────────────
    print("[Dashboard] Oluşturuluyor...")
    try:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_dashboard.py")
        subprocess.run(["python3", script], check=False, timeout=30)
    except Exception as e:
        print(f"  [WARN] Dashboard oluşturulamadı: {e}")

    print("\n=== SNAPSHOT TAMAMLANDI ===")


if __name__ == "__main__":
    main()

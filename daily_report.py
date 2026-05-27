#!/usr/bin/env python3
import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

DECISIONS_FILE = os.path.join(os.path.dirname(__file__), "decisions.jsonl")
SETUPS_FILE    = os.path.join(os.path.dirname(__file__), "setups.jsonl")
TZ_LOCAL = timezone(timedelta(hours=3))

WATCHLIST_BY_CATEGORY = {
    "MAJORS":   ["BTCUSDT", "ETHUSDT"],
    "L1 ALTS":  ["SOLUSDT", "BNBUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "SUIUSDT", "ADAUSDT", "TRXUSDT"],
    "DEFI":     ["LINKUSDT", "UNIUSDT", "DOTUSDT"],
    "STORIES":  ["TONUSDT", "HBARUSDT", "ATOMUSDT", "XLMUSDT", "XRPUSDT"],
    "MEMES":    ["DOGEUSDT"],
    "LEGACY":   ["LTCUSDT"],
}
CONSENSUS_ORDER = ["STRONG BULLISH", "BULLISH", "MIXED", "BEARISH", "STRONG BEARISH"]


def coin(sym):
    return sym.replace("USDT", "")


def telegram_send(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [WARN] Telegram credentials eksik.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        r = requests.post(url, data=payload, timeout=10)
        ok = r.json().get("ok")
        print(f"  [{'OK' if ok else 'ERR'}] Telegram {'gönderildi' if ok else r.json()}")
    except Exception as e:
        print(f"  [ERR] Telegram: {e}")


def telegram_send_long(text):
    if len(text) <= 4096:
        telegram_send(text)
        return
    mid = text.rfind("\n", 0, 4000)
    if mid == -1:
        mid = 4000
    telegram_send(text[:mid])
    telegram_send(text[mid:].lstrip("\n"))


def parse_ts(ts_str):
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def get_period(arg=None):
    now = datetime.now(TZ_LOCAL)
    if arg == "morning":
        is_morning = True
    elif arg == "evening":
        is_morning = False
    else:
        is_morning = now.hour < 15

    if is_morning:
        end   = now
        start = end - timedelta(hours=12)
        title = f"GÜNAYDIN RAPORU — {now.strftime('%d.%m.%Y')} 09:00"
        label = f"gece dönemi: {start.strftime('%d.%m %H:%M')} - {now.strftime('%d.%m %H:%M')}"
        period_name = "GECE"
    else:
        end   = now
        start = now.replace(hour=9, minute=0, second=0, microsecond=0)
        title = f"İYİ AKŞAMLAR RAPORU — {now.strftime('%d.%m.%Y')} 21:00"
        label = f"gündüz dönemi: {start.strftime('%d.%m %H:%M')} - {now.strftime('%d.%m %H:%M')}"
        period_name = "GÜNDÜZ"

    return is_morning, start, end, title, label, period_name


def load_decisions():
    records = []
    if not os.path.exists(DECISIONS_FILE):
        return records
    with open(DECISIONS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
    is_morning, start, end, title, period_label, period_name = get_period(arg)

    print(f"\n=== {title} ===\n")

    all_records = load_decisions()
    if not all_records:
        print("decisions.jsonl boş veya bulunamadı.")
        return

    # Latest record per symbol (from all time)
    latest_by_sym = {}
    for r in all_records:
        sym = r.get("symbol")
        if not sym:
            continue
        try:
            ts = parse_ts(r["timestamp"])
            if sym not in latest_by_sym or ts > parse_ts(latest_by_sym[sym]["timestamp"]):
                latest_by_sym[sym] = r
        except Exception:
            pass

    # Period records
    period_records = []
    for r in all_records:
        try:
            ts = parse_ts(r["timestamp"])
            if start <= ts <= end:
                period_records.append(r)
        except Exception:
            pass

    # Period records per symbol, sorted by time
    period_by_sym = {}
    for r in period_records:
        sym = r.get("symbol")
        if sym:
            period_by_sym.setdefault(sym, []).append(r)
    for sym in period_by_sym:
        period_by_sym[sym].sort(key=lambda x: parse_ts(x["timestamp"]))

    # ── Analysis ──────────────────────────────────────────────────────────────

    # Current bias distribution
    bias_counts = {}
    for r in latest_by_sym.values():
        c = r.get("consensus", "MIXED")
        bias_counts[c] = bias_counts.get(c, 0) + 1

    # Consensus flips in period
    flips = []
    for sym, records in period_by_sym.items():
        if len(records) < 2:
            continue
        first = records[0].get("consensus", "MIXED")
        last  = records[-1].get("consensus", "MIXED")
        if first != last:
            flips.append((sym, first, last))

    # Price changes over period
    price_changes = []
    for sym, records in period_by_sym.items():
        if len(records) < 2:
            continue
        p_start = records[0].get("price", 0)
        p_end   = records[-1].get("price", 0)
        if p_start > 0:
            pct = (p_end - p_start) / p_start * 100
            price_changes.append((sym, pct))
    price_changes.sort(key=lambda x: x[1])

    # Triggered setups in period (unique symbols, first occurrence)
    setup_syms = {}
    for r in period_records:
        s = r.get("setup")
        if s and r["symbol"] not in setup_syms:
            setup_syms[r["symbol"]] = s

    # Active STRONG consensus
    strong_bull = [s for s, r in latest_by_sym.items() if r.get("consensus") == "STRONG BULLISH"]
    strong_bear = [s for s, r in latest_by_sym.items() if r.get("consensus") == "STRONG BEARISH"]

    # RSI extremes
    rsi_low  = sorted([(s, r["rsi14"]) for s, r in latest_by_sym.items() if r.get("rsi14", 50) < 30], key=lambda x: x[1])
    rsi_high = sorted([(s, r["rsi14"]) for s, r in latest_by_sym.items() if r.get("rsi14", 50) > 70], key=lambda x: -x[1])

    # ── Build report ──────────────────────────────────────────────────────────
    sep = "═" * 39
    lines = [sep, title, f"({period_label})", sep]

    # Current status
    lines.append("\nŞU ANKİ DURUM")
    parts = [f"{bias_counts[k]} {k.lower()}" for k in CONSENSUS_ORDER if k in bias_counts]
    lines.append(", ".join(parts) or "veri yok")

    # Period changes
    lines.append(f"\n{period_name} DEĞİŞİMLERİ")
    lines.append(f"Bias flip: {len(flips)}")
    if flips:
        details = ", ".join(f"{coin(s)} {a[:4]}→{b[:4]}" for s, a, b in flips[:6])
        if len(flips) > 6:
            details += "..."
        lines.append(f"  ({details})")
    lines.append(f"Tetiklenen setup: {len(setup_syms)}")
    if setup_syms:
        for sym, s in setup_syms.items():
            lines.append(f"  {coin(sym)} {s['direction']}  entry {s['entry']}  R:R {s['rr']}:1")

    # Price changes
    losers  = [(s, p) for s, p in price_changes if p < 0][:5]
    winners = [(s, p) for s, p in reversed(price_changes) if p > 0][:5]

    if losers:
        lines.append("\nEN ÇOK DÜŞENLER (12h)")
        for sym, pct in losers:
            lines.append(f"{coin(sym):<6} {pct:+.2f}%")
    if winners:
        lines.append("\nEN ÇOK ÇIKANLAR (12h)")
        for sym, pct in winners:
            lines.append(f"{coin(sym):<6} {pct:+.2f}%")
    if not losers and not winners:
        lines.append("\nFiyat değişimi: dönem verisi yetersiz")

    # Category summary
    lines.append("\nKATEGORİ DURUMU")
    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        now_biases = [latest_by_sym[s].get("consensus", "MIXED") for s in symbols if s in latest_by_sym]
        if not now_biases:
            continue
        tally = {}
        for b in now_biases:
            tally[b] = tally.get(b, 0) + 1
        cat_parts = [f"{tally[k]} {k.lower()}" for k in CONSENSUS_ORDER if k in tally]
        notable = [coin(s) for s in symbols if s in latest_by_sym and "BULLISH" in latest_by_sym[s].get("consensus", "")]
        suffix = f" ({', '.join(notable)})" if notable else ""
        lines.append(f"{cat}: {', '.join(cat_parts)}{suffix}")

    # RSI extremes
    lines.append("\nUÇ RSI DEĞERLERİ")
    lines.append("Oversold  (<30): " + (", ".join(f"{coin(s)} {v:.1f}" for s, v in rsi_low) or "yok"))
    lines.append("Overbought(>70): " + (", ".join(f"{coin(s)} {v:.1f}" for s, v in rsi_high) or "yok"))

    # Strong consensus
    lines.append("\nAKTİF STRONG KONSENSUS")
    if strong_bull:
        lines.append(f"STRONG BULLISH ({len(strong_bull)}): " + ", ".join(coin(s) for s in strong_bull))
    if strong_bear:
        coins_str = ", ".join(coin(s) for s in strong_bear)
        low_vol_n = sum(1 for s in strong_bear if latest_by_sym.get(s, {}).get("volume_signal") == "LOW VOL")
        vol_note = f"\n  ({low_vol_n}/{len(strong_bear)} LOW VOL — setup tetiklenmedi)" if low_vol_n else ""
        lines.append(f"STRONG BEARISH ({len(strong_bear)}): {coins_str}{vol_note}")
    if not strong_bull and not strong_bear:
        lines.append("Yok")

    # Performance summary from setups.jsonl
    if os.path.exists(SETUPS_FILE):
        all_setups_rec = []
        with open(SETUPS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        all_setups_rec.append(json.loads(line))
                    except Exception:
                        pass

        if all_setups_rec:
            total   = len(all_setups_rec)
            active  = sum(1 for s in all_setups_rec if s["status"] == "active")
            wins    = sum(1 for s in all_setups_rec if s["status"] == "win")
            losses  = sum(1 for s in all_setups_rec if s["status"] == "loss")
            timeouts= sum(1 for s in all_setups_rec if s["status"] == "timeout")
            closed  = wins + losses + timeouts
            win_rate = int(wins / closed * 100) if closed > 0 else 0
            closed_rrs   = [s["actual_rr"] for s in all_setups_rec if s["status"] != "active" and s.get("actual_rr") is not None]
            planned_rrs  = [s["rr_planned"] for s in all_setups_rec if s.get("rr_planned") is not None]
            net_edge     = round(sum(closed_rrs), 2) if closed_rrs else 0
            avg_actual   = round(sum(closed_rrs) / len(closed_rrs), 2) if closed_rrs else None
            avg_planned  = round(sum(planned_rrs) / len(planned_rrs), 2) if planned_rrs else None

            # Last 7 days
            cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
            rec_7d = []
            for s in all_setups_rec:
                try:
                    ts = datetime.fromisoformat(s["timestamp"]).astimezone(timezone.utc)
                    if ts >= cutoff_7d:
                        rec_7d.append(s)
                except Exception:
                    pass
            w7 = sum(1 for s in rec_7d if s["status"] == "win")
            l7 = sum(1 for s in rec_7d if s["status"] == "loss")
            t7 = sum(1 for s in rec_7d if s["status"] == "timeout")
            c7 = w7 + l7 + t7
            wr7 = int(w7 / c7 * 100) if c7 > 0 else 0
            rrs7 = [s["actual_rr"] for s in rec_7d if s["status"] != "active" and s.get("actual_rr") is not None]
            net7 = round(sum(rrs7), 2) if rrs7 else 0

            lines.append("\nPERFORMANS ÖZETİ (TÜM ZAMANLAR)")
            lines.append(f"Toplam setup: {total}")
            lines.append(f"Aktif: {active}  Win: {wins}  Loss: {losses}  Timeout: {timeouts}")
            if closed > 0:
                lines.append(f"Kazanma oranı: %{win_rate} ({wins}/{closed} kapanan)")
                if avg_actual is not None:
                    lines.append(f"Ortalama R:R: {avg_actual} (planlanan: {avg_planned})")
                lines.append(f"Net edge: {net_edge:+.2f}R (gerçek)")
            else:
                lines.append("Henüz kapanan setup yok.")

            lines.append(f"\nSON 7 GÜN")
            lines.append(f"Setup: {len(rec_7d)} (W: {w7}, L: {l7}, T: {t7})")
            if c7 > 0:
                lines.append(f"Kazanma: %{wr7} | Net: {net7:+.2f}R")
            else:
                lines.append("Henüz kapanan setup yok.")

            # Setup type breakdown
            type_stats = {}
            for s in all_setups_rec:
                t = s.get("type", "STRONG_TREND")
                if t not in type_stats:
                    type_stats[t] = {"total": 0, "win": 0, "loss": 0}
                type_stats[t]["total"] += 1
                if s.get("status") == "win":
                    type_stats[t]["win"] += 1
                elif s.get("status") == "loss":
                    type_stats[t]["loss"] += 1

            lines.append("\nSETUP TİPİ DAĞILIMI")
            for t in ["STRONG_TREND", "BREAKOUT", "REVERSAL", "PULLBACK", "WEAK_TREND"]:
                stats = type_stats.get(t)
                if not stats:
                    continue
                w_t, l_t, tot_t = stats["win"], stats["loss"], stats["total"]
                closed_t = w_t + l_t
                wr_t = int(w_t / closed_t * 100) if closed_t > 0 else 0
                wr_str = f"%{wr_t}" if closed_t > 0 else "-"
                lines.append(f"{t}: {tot_t} (W:{w_t}, L:{l_t}) → {wr_str}")

    lines += ["", sep]

    report = "\n".join(lines)
    print(report)

    print("\n[Telegram] Gönderiliyor...")
    telegram_send_long(report)
    print("\n=== RAPOR TAMAMLANDI ===")


if __name__ == "__main__":
    main()

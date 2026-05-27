#!/usr/bin/env python3
"""Generates docs/index.html from decisions.jsonl and setups.jsonl."""
import os
import json
from datetime import datetime, timezone, timedelta
from html import escape

DECISIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decisions.jsonl")
SETUPS_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setups.jsonl")
OUTPUT_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "index.html")

TZ_LOCAL = timezone(timedelta(hours=3))

WATCHLIST_BY_CATEGORY = {
    "MAJORS":   ["BTCUSDT", "ETHUSDT"],
    "L1 ALTS":  ["SOLUSDT", "BNBUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "SUIUSDT", "ADAUSDT", "TRXUSDT"],
    "DEFI":     ["LINKUSDT", "UNIUSDT", "DOTUSDT"],
    "STORIES":  ["TONUSDT", "HBARUSDT", "ATOMUSDT", "XLMUSDT", "XRPUSDT"],
    "MEMES":    ["DOGEUSDT"],
    "LEGACY":   ["LTCUSDT"],
}
ALL_SYMBOLS = [s for syms in WATCHLIST_BY_CATEGORY.values() for s in syms]

CONSENSUS_COLORS = {
    "STRONG BULLISH": "#059669",
    "BULLISH":        "#10b981",
    "MIXED":          "#64748b",
    "BEARISH":        "#ef4444",
    "STRONG BEARISH": "#dc2626",
}
BIAS_COLORS = {"bullish": "#10b981", "bearish": "#ef4444", "neutral": "#64748b"}


def coin(sym):
    return sym.replace("USDT", "")


def parse_ts(ts_str):
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def fmt_price(sym, price):
    if sym == "BTCUSDT":                                         return f"${price:,.2f}"
    if sym in ("ETHUSDT", "BNBUSDT", "SOLUSDT", "LTCUSDT"):     return f"${price:.2f}"
    if price >= 1:                                               return f"${price:.4f}"
    if price >= 0.01:                                            return f"${price:.4f}"
    return f"${price:.6f}"


def load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def pct_html(pct):
    color = "#10b981" if pct >= 0 else "#ef4444"
    return f'<span style="color:{color}">{pct:+.2f}%</span>'


def bias_badge(bias):
    color = BIAS_COLORS.get(bias, "#64748b")
    letter = {"bullish": "B", "bearish": "b", "neutral": "·"}.get(bias, "?")
    title = bias or ""
    return f'<span title="{title}" style="color:{color};font-weight:700;font-size:0.9em">{letter}</span>'


def consensus_badge(c):
    color = CONSENSUS_COLORS.get(c, "#64748b")
    return (f'<span style="background:{color}22;color:{color};border:1px solid {color}55;'
            f'padding:2px 7px;border-radius:999px;font-size:0.72em;font-weight:600;white-space:nowrap">'
            f'{escape(c)}</span>')


def vol_badge(vol):
    if vol == "HIGH VOL":  return '<span style="color:#10b981;font-weight:600;font-size:0.78em">HIGH</span>'
    if vol == "LOW VOL":   return '<span style="color:#374151;font-size:0.78em">LOW</span>'
    return '<span style="color:#64748b;font-size:0.78em">NRM</span>'


def heatmap_cell(count, kind):
    if count == 0:
        return f'<td style="text-align:center;padding:8px 14px;color:#374151">·</td>'
    if kind in ("STRONG BULLISH", "BULLISH"):
        r, g, b = 16, 185, 129
    elif kind in ("STRONG BEARISH", "BEARISH"):
        r, g, b = 239, 68, 68
    else:
        r, g, b = 100, 116, 139
    op = min(0.2 + count * 0.18, 0.95)
    style = (f"background:rgba({r},{g},{b},{op:.2f});color:#f8fafc;font-weight:700;"
             f"text-align:center;padding:8px 14px;border-radius:6px")
    return f'<td style="{style}">{count}</td>'


def main():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    decisions = load_jsonl(DECISIONS_FILE)
    setups    = load_jsonl(SETUPS_FILE)

    if not decisions:
        print("[build_dashboard] decisions.jsonl boş, atlanıyor.")
        return

    # ── Latest snapshot per symbol ────────────────────────────────────────────
    latest = {}
    for r in decisions:
        sym = r.get("symbol")
        if not sym:
            continue
        try:
            ts = parse_ts(r["timestamp"])
            if sym not in latest or ts > parse_ts(latest[sym]["timestamp"]):
                latest[sym] = r
        except Exception:
            pass

    now_ts = max(parse_ts(r["timestamp"]) for r in latest.values()) if latest else datetime.now(TZ_LOCAL)
    update_str = now_ts.astimezone(TZ_LOCAL).strftime("%Y-%m-%d %H:%M UTC+3")

    # ── 24h price changes ─────────────────────────────────────────────────────
    target_24h = now_ts - timedelta(hours=24)
    changes_24h = {}
    for sym in ALL_SYMBOLS:
        sym_recs = [r for r in decisions if r.get("symbol") == sym]
        if len(sym_recs) < 2:
            continue
        old_rec  = min(sym_recs, key=lambda r: abs((parse_ts(r["timestamp"]) - target_24h).total_seconds()))
        p_old    = old_rec.get("price", 0)
        p_new    = latest.get(sym, {}).get("price", 0)
        if p_old > 0 and p_new > 0:
            changes_24h[sym] = (p_new - p_old) / p_old * 100

    # ── Bias distribution ─────────────────────────────────────────────────────
    bias_counts = {}
    for r in latest.values():
        c = r.get("consensus", "MIXED")
        bias_counts[c] = bias_counts.get(c, 0) + 1

    total_bull = bias_counts.get("STRONG BULLISH", 0) + bias_counts.get("BULLISH", 0)
    total_bear = bias_counts.get("STRONG BEARISH", 0) + bias_counts.get("BEARISH", 0)
    total_neut = bias_counts.get("MIXED", 0)

    # ── Setup stats ───────────────────────────────────────────────────────────
    active_setups = [s for s in setups if s.get("status") == "active"]
    wins     = sum(1 for s in setups if s.get("status") == "win")
    losses   = sum(1 for s in setups if s.get("status") == "loss")
    closed   = wins + losses + sum(1 for s in setups if s.get("status") == "timeout")
    wr_str   = f"%{int(wins/closed*100)} ({wins}/{closed})" if closed > 0 else "—"
    net_rr   = round(sum(s["actual_rr"] for s in setups
                         if s.get("status") != "active" and s.get("actual_rr") is not None), 2)

    # 7-day win rate
    cutoff7 = datetime.now(timezone.utc) - timedelta(days=7)
    r7 = [s for s in setups if parse_ts(s["timestamp"]).astimezone(timezone.utc) >= cutoff7]
    w7 = sum(1 for s in r7 if s.get("status") == "win")
    c7 = sum(1 for s in r7 if s.get("status") in ("win", "loss", "timeout"))
    wr7_str = f"%{int(w7/c7*100)} ({w7}/{c7})" if c7 > 0 else "—"

    # ── Category heatmap ─────────────────────────────────────────────────────
    HEATMAP_COLS = ["STRONG BULLISH", "BULLISH", "MIXED", "BEARISH", "STRONG BEARISH"]
    HEATMAP_LABELS = ["S.BULL", "BULL", "MIX", "BEAR", "S.BEAR"]
    HEATMAP_COLORS = ["#059669", "#10b981", "#64748b", "#ef4444", "#dc2626"]

    header_cells = "".join(
        f'<th style="color:{c};font-size:0.72em;padding:6px 14px;font-weight:600">{lb}</th>'
        for lb, c in zip(HEATMAP_LABELS, HEATMAP_COLORS)
    )
    heatmap_rows = ""
    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        counts = {col: 0 for col in HEATMAP_COLS}
        for sym in symbols:
            if sym in latest:
                c = latest[sym].get("consensus", "MIXED")
                if c in counts:
                    counts[c] += 1
        cells = "".join(heatmap_cell(counts[col], col) for col in HEATMAP_COLS)
        heatmap_rows += f'<tr><td style="color:#8b949e;font-size:0.8em;padding:8px 16px 8px 0;white-space:nowrap">{escape(cat)}</td>{cells}</tr>\n'

    # ── Coin table rows ───────────────────────────────────────────────────────
    coin_rows = ""
    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        for sym in symbols:
            if sym not in latest:
                continue
            r       = latest[sym]
            price   = r.get("price", 0)
            ema50   = r.get("ema50", 0)
            ema_pct = (price - ema50) / ema50 * 100 if ema50 > 0 else 0
            rsi     = r.get("rsi14", 0)
            tf      = r.get("tf_biases", {})
            cons    = r.get("consensus", "MIXED")
            vol     = r.get("volume_signal", "")
            chg     = changes_24h.get(sym)
            rsi_col = "#ef4444" if rsi > 70 else ("#10b981" if rsi < 30 else "#c9d1d9")
            rsi_fw  = "700" if (rsi > 70 or rsi < 30) else "400"
            chg_html = pct_html(chg) if chg is not None else '<span style="color:#374151">—</span>'
            coin_rows += f"""
            <tr style="border-bottom:1px solid #21262d">
              <td style="padding:10px 12px;white-space:nowrap">
                <span style="font-weight:700;color:#e6edf3">{coin(sym)}</span>
                <span style="color:#374151;font-size:0.72em;margin-left:6px">{escape(cat)}</span>
              </td>
              <td style="padding:10px 12px;font-family:monospace;color:#c9d1d9">{escape(fmt_price(sym, price))}</td>
              <td style="padding:10px 12px">{pct_html(ema_pct)}</td>
              <td style="padding:10px 12px;color:{rsi_col};font-weight:{rsi_fw}">{rsi:.1f}</td>
              <td style="padding:10px 12px;text-align:center">{bias_badge(tf.get('15m',''))}</td>
              <td style="padding:10px 12px;text-align:center">{bias_badge(tf.get('1h',''))}</td>
              <td style="padding:10px 12px;text-align:center">{bias_badge(tf.get('4h',''))}</td>
              <td style="padding:10px 12px">{consensus_badge(cons)}</td>
              <td style="padding:10px 12px">{vol_badge(vol)}</td>
              <td style="padding:10px 12px">{chg_html}</td>
            </tr>"""

    # ── Active setups ─────────────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    if active_setups:
        setup_rows = ""
        for s in active_setups:
            age_h = int((now_utc - parse_ts(s["timestamp"]).astimezone(timezone.utc)).total_seconds() / 3600)
            dc = "#10b981" if s["direction"] == "LONG" else "#ef4444"
            setup_rows += f"""
            <tr style="border-bottom:1px solid #21262d">
              <td style="padding:10px 12px;font-weight:700">{coin(s['symbol'])}</td>
              <td style="padding:10px 12px;color:{dc};font-weight:600">{s['direction']}</td>
              <td style="padding:10px 12px;font-family:monospace">{s['entry']}</td>
              <td style="padding:10px 12px;font-family:monospace;color:#ef4444">{s['stop']}</td>
              <td style="padding:10px 12px;font-family:monospace;color:#10b981">{s['target']}</td>
              <td style="padding:10px 12px;color:#f59e0b;font-weight:600">{s['rr_planned']}:1</td>
              <td style="padding:10px 12px;color:#64748b">{age_h}s önce</td>
            </tr>"""
        setups_html = f"""<table><thead>
          <tr style="border-bottom:1px solid #30363d">
            {''.join(f'<th style="text-align:left;padding:8px 12px;color:#64748b;font-size:0.75em">{h}</th>' for h in ['SYM','DIR','ENTRY','STOP','TARGET','R:R','AGE'])}
          </tr></thead><tbody>{setup_rows}</tbody></table>"""
    else:
        setups_html = '<p style="color:#374151;font-style:italic;padding:8px 0">Şu an aktif setup yok.</p>'

    # ── Performance block ─────────────────────────────────────────────────────
    if setups:
        net_color = "#10b981" if net_rr >= 0 else "#ef4444"
        stats = [
            ("TOPLAM", str(len(setups)), "#8b949e"),
            ("AKTİF",  str(len(active_setups)), "#64748b"),
            ("WIN",    str(wins),   "#10b981"),
            ("LOSS",   str(losses), "#ef4444"),
            ("W.RATE", wr_str,      "#f59e0b"),
            ("NET R",  f"{net_rr:+.2f}R", net_color),
        ]
        perf_html = '<div style="display:flex;gap:28px;flex-wrap:wrap">' + "".join(
            f'<div><div style="color:#64748b;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:4px">{k}</div>'
            f'<div style="font-size:1.4em;font-weight:700;color:{c}">{escape(v)}</div></div>'
            for k, v, c in stats
        ) + "</div>"
    else:
        perf_html = '<p style="color:#374151;font-style:italic">Henüz setup verisi yok.</p>'

    # ── Top movers ────────────────────────────────────────────────────────────
    sorted_chg = sorted(changes_24h.items(), key=lambda x: x[1])
    losers  = sorted_chg[:5]
    winners = list(reversed(sorted_chg))[:5]
    winners = [(s, p) for s, p in winners if p > 0]

    def mover_row(sym, pct):
        return (f'<div style="display:flex;justify-content:space-between;padding:6px 0;'
                f'border-bottom:1px solid #21262d">'
                f'<span style="color:#c9d1d9;font-weight:600">{coin(sym)}</span>'
                f'{pct_html(pct)}</div>')

    movers_html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px">'
    movers_html += '<div><div style="color:#ef4444;font-size:0.75em;font-weight:600;margin-bottom:8px">TOP LOSERS (24h)</div>'
    movers_html += "".join(mover_row(s, p) for s, p in losers if p < 0) or '<span style="color:#374151">Yok</span>'
    movers_html += '</div><div><div style="color:#10b981;font-size:0.75em;font-weight:600;margin-bottom:8px">TOP WINNERS (24h)</div>'
    movers_html += "".join(mover_row(s, p) for s, p in winners) or '<span style="color:#374151">Yok</span>'
    movers_html += '</div></div>'

    # ── Full HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <meta http-equiv="refresh" content="3600">
  <title>Bybit Trading Monitor</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {{ background:#0d1117; color:#e6edf3; font-family:system-ui,-apple-system,sans-serif; margin:0; }}
    .panel {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:24px; margin-bottom:20px; }}
    .section-title {{ color:#8b949e; font-size:0.72em; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:16px; }}
    table {{ width:100%; border-collapse:collapse; }}
    tr:hover {{ background:rgba(255,255,255,0.025); }}
    ::-webkit-scrollbar {{ height:4px; width:4px; }}
    ::-webkit-scrollbar-thumb {{ background:#30363d; border-radius:2px; }}
  </style>
</head>
<body style="min-height:100vh;padding:24px;max-width:1200px;margin:0 auto">

  <!-- HEADER -->
  <div style="margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid #21262d">
    <h1 style="font-size:1.4em;font-weight:700;color:#e6edf3;margin:0 0 4px">Bybit Trading Monitor</h1>
    <p style="color:#64748b;font-size:0.85em;margin:0">Live Dashboard &middot; {escape(update_str)}</p>
  </div>

  <!-- SUMMARY CARDS -->
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:20px">
    <div style="background:#10b98122;border:1px solid #10b98144;border-radius:10px;padding:18px 20px">
      <div style="color:#10b981;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:6px">Bullish</div>
      <div style="color:#e6edf3;font-size:2em;font-weight:700">{total_bull}</div>
    </div>
    <div style="background:#ef444422;border:1px solid #ef444444;border-radius:10px;padding:18px 20px">
      <div style="color:#ef4444;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:6px">Bearish</div>
      <div style="color:#e6edf3;font-size:2em;font-weight:700">{total_bear}</div>
    </div>
    <div style="background:#64748b22;border:1px solid #64748b44;border-radius:10px;padding:18px 20px">
      <div style="color:#64748b;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:6px">Neutral/Mixed</div>
      <div style="color:#e6edf3;font-size:2em;font-weight:700">{total_neut}</div>
    </div>
    <div style="background:#f59e0b22;border:1px solid #f59e0b44;border-radius:10px;padding:18px 20px">
      <div style="color:#f59e0b;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:6px">Win Rate 7d</div>
      <div style="color:#e6edf3;font-size:1.5em;font-weight:700">{escape(wr7_str)}</div>
    </div>
  </div>

  <!-- TOP MOVERS + HEATMAP (side by side on desktop) -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
    <div class="panel" style="margin-bottom:0">
      <div class="section-title">Top Movers (24h)</div>
      {movers_html}
    </div>
    <div class="panel" style="margin-bottom:0;overflow-x:auto">
      <div class="section-title">Kategori Heatmap</div>
      <table>
        <thead><tr>
          <th style="text-align:left;padding:6px 0;width:80px"></th>
          {header_cells}
        </tr></thead>
        <tbody>{heatmap_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- COIN TABLE -->
  <div class="panel" style="overflow-x:auto">
    <div class="section-title">Coin Durumu</div>
    <table>
      <thead>
        <tr style="border-bottom:1px solid #21262d">
          {''.join(f'<th style="text-align:{"center" if h in ["15m","1h","4h"] else "left"};padding:8px 12px;color:#64748b;font-size:0.72em">{h}</th>' for h in ["SYMBOL","PRICE","EMA%","RSI","15m","1h","4h","CONSENSUS","VOL","24h%"])}
        </tr>
      </thead>
      <tbody>{coin_rows}</tbody>
    </table>
  </div>

  <!-- ACTIVE SETUPS -->
  <div class="panel" style="overflow-x:auto">
    <div class="section-title">Aktif Setuplar ({len(active_setups)})</div>
    {setups_html}
  </div>

  <!-- PERFORMANCE -->
  <div class="panel">
    <div class="section-title">Performans Özeti</div>
    {perf_html}
  </div>

  <!-- FOOTER -->
  <div style="text-align:center;color:#374151;font-size:0.75em;padding:20px 0">
    Auto-generated by GitHub Actions &middot; Updated hourly
  </div>

</body>
</html>"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[build_dashboard] docs/index.html yazıldı ({len(html):,} karakter)")


if __name__ == "__main__":
    main()

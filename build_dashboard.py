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
    "STRONG BULLISH": "#059669", "BULLISH": "#10b981",
    "MIXED": "#64748b",
    "BEARISH": "#ef4444", "STRONG BEARISH": "#dc2626",
}
BIAS_COLORS = {"bullish": "#10b981", "bearish": "#ef4444", "neutral": "#64748b"}
HEATMAP_COLS   = ["STRONG BULLISH", "BULLISH", "MIXED", "BEARISH", "STRONG BEARISH"]
HEATMAP_LABELS = ["S.BULL", "BULL", "MIX", "BEAR", "S.BEAR"]
HEATMAP_COLORS = ["#059669", "#10b981", "#64748b", "#ef4444", "#dc2626"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def coin(sym): return sym.replace("USDT", "")

def parse_ts(ts_str):
    try:    return datetime.fromisoformat(ts_str)
    except: return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

def fmt_price(sym, price):
    if sym == "BTCUSDT":                                     return f"${price:,.2f}"
    if sym in ("ETHUSDT","BNBUSDT","SOLUSDT","LTCUSDT"):     return f"${price:.2f}"
    if price >= 1:                                           return f"${price:.4f}"
    if price >= 0.01:                                        return f"${price:.4f}"
    return f"${price:.6f}"

def load_jsonl(path):
    rows = []
    if not os.path.exists(path): return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except: pass
    return rows

def pct_html(pct, bold=False):
    c = "#10b981" if pct >= 0 else "#ef4444"
    fw = "700" if bold else "400"
    return f'<span style="color:{c};font-weight:{fw}">{pct:+.2f}%</span>'

def bias_badge(bias):
    c = BIAS_COLORS.get(bias, "#64748b")
    letter = {"bullish": "B", "bearish": "b", "neutral": "·"}.get(bias, "?")
    return f'<span title="{bias}" style="color:{c};font-weight:700;font-size:0.9em">{letter}</span>'

def consensus_badge(c):
    col = CONSENSUS_COLORS.get(c, "#64748b")
    return (f'<span style="background:{col}22;color:{col};border:1px solid {col}55;'
            f'padding:2px 7px;border-radius:999px;font-size:0.72em;font-weight:600;white-space:nowrap">'
            f'{escape(c)}</span>')

def vol_badge(vol):
    if vol == "HIGH VOL": return '<span style="color:#10b981;font-weight:600;font-size:0.78em">HIGH</span>'
    if vol == "LOW VOL":  return '<span style="color:#374151;font-size:0.78em">LOW</span>'
    return '<span style="color:#64748b;font-size:0.78em">NRM</span>'

def heatmap_cell_visual(count, kind):
    if count == 0:
        return '<td style="padding:4px 6px"><div style="width:38px;height:26px;background:#1e2530;border-radius:4px"></div></td>'
    if "BULLISH" in kind:   r, g, b = 16, 185, 129
    elif "BEARISH" in kind: r, g, b = 239, 68, 68
    else:                   r, g, b = 100, 116, 139
    op = min(0.3 + count * 0.22, 1.0)
    bg = f"rgba({r},{g},{b},{op:.2f})"
    return (f'<td style="padding:4px 6px">'
            f'<div title="{count} coin" style="width:38px;height:26px;background:{bg};'
            f'border-radius:4px;cursor:default;display:flex;align-items:center;justify-content:center;'
            f'color:rgba(255,255,255,0.8);font-size:0.75em;font-weight:700">{count}</div></td>')

def flip_direction(old_c, new_c):
    bull = {"STRONG BULLISH", "BULLISH"}
    bear = {"STRONG BEARISH", "BEARISH"}
    if old_c in bull and new_c in bear: return "#ef4444", "↓"
    if old_c in bear and new_c in bull: return "#10b981", "↑"
    return "#64748b", "↔"


# ── Coin detail page ──────────────────────────────────────────────────────────

def coin_page_html(sym, stats, sym_setups, changes_24h):
    cname    = sym.replace("USDT", "")
    price    = stats.get("price", 0) if stats else 0
    ema50    = stats.get("ema50", 0) if stats else 0
    rsi14    = stats.get("rsi14", 0) if stats else 0
    vol      = stats.get("volume_signal", "—") if stats else "—"
    cons     = stats.get("consensus", "—") if stats else "—"
    tf_b     = stats.get("tf_biases", {}) if stats else {}
    chg      = changes_24h.get(sym)
    chg_str  = f"{chg:+.2f}%" if chg is not None else "—"
    chg_col  = "#10b981" if (chg or 0) >= 0 else "#ef4444"
    ema_pct  = (price - ema50) / ema50 * 100 if ema50 > 0 else 0
    cons_col = CONSENSUS_COLORS.get(cons, "#64748b")
    now_utc  = datetime.now(timezone.utc)
    sets_json = json.dumps(sym_setups)

    # Active setups table
    active = [s for s in sym_setups if s.get("status") == "active"]
    if active:
        ths_a = "".join(f'<th style="text-align:left;padding:8px 12px;color:#64748b;font-size:0.72em">{h}</th>'
                        for h in ["DIR", "ENTRY", "SL", "TP", "R:R", "AGE"])
        arows = ""
        for s in active:
            age_h = int((now_utc - parse_ts(s["timestamp"]).astimezone(timezone.utc)).total_seconds() / 3600)
            dc = "#10b981" if s["direction"] == "LONG" else "#ef4444"
            arows += (f'<tr class="trow">'
                      f'<td style="padding:8px 12px;color:{dc};font-weight:600">{s["direction"]}</td>'
                      f'<td style="padding:8px 12px;font-family:monospace">{s["entry"]}</td>'
                      f'<td style="padding:8px 12px;font-family:monospace;color:#ef4444">{s["stop"]}</td>'
                      f'<td style="padding:8px 12px;font-family:monospace;color:#10b981">{s["target"]}</td>'
                      f'<td style="padding:8px 12px;color:#f59e0b;font-weight:600">{s.get("rr_planned","—")}:1</td>'
                      f'<td style="padding:8px 12px;color:#64748b">{age_h}s önce</td></tr>')
        active_html = (f'<div style="overflow-x:auto"><table>'
                       f'<thead><tr style="border-bottom:1px solid #30363d">{ths_a}</tr></thead>'
                       f'<tbody>{arows}</tbody></table></div>')
    else:
        active_html = '<p style="color:#374151;font-style:italic;padding:8px 0">Aktif setup yok.</p>'

    # Closed setups table
    closed = sorted([s for s in sym_setups if s.get("status") in ("win", "loss", "timeout")],
                    key=lambda x: x.get("timestamp", ""), reverse=True)[:50]
    if closed:
        ths_c = "".join(f'<th style="text-align:left;padding:8px 12px;color:#64748b;font-size:0.72em">{h}</th>'
                        for h in ["TARİH", "DIR", "ENTRY", "RESULT", "P&L"])
        crows = ""
        for s in closed:
            status = s.get("status", "")
            sc  = {"win": "#10b981", "loss": "#ef4444", "timeout": "#64748b"}.get(status, "#64748b")
            slb = {"win": "WIN", "loss": "LOSS", "timeout": "TIMEOUT"}.get(status, status.upper())
            ts_l = parse_ts(s["timestamp"]).astimezone(TZ_LOCAL).strftime("%d.%m %H:%M")
            arr  = s.get("actual_rr")
            rr_s = f"{arr:+.2f}R" if arr is not None else "—"
            dc   = "#10b981" if s["direction"] == "LONG" else "#ef4444"
            crows += (f'<tr class="trow">'
                      f'<td style="padding:8px 12px;color:#64748b;font-size:0.85em">{ts_l}</td>'
                      f'<td style="padding:8px 12px;color:{dc};font-weight:600">{s["direction"]}</td>'
                      f'<td style="padding:8px 12px;font-family:monospace">{s["entry"]}</td>'
                      f'<td style="padding:8px 12px;color:{sc};font-weight:600">{slb}</td>'
                      f'<td style="padding:8px 12px;color:{sc};font-weight:600">{rr_s}</td></tr>')
        closed_html = (f'<div style="overflow-x:auto"><table>'
                       f'<thead><tr style="border-bottom:1px solid #30363d">{ths_c}</tr></thead>'
                       f'<tbody>{crows}</tbody></table></div>')
    else:
        closed_html = '<p style="color:#374151;font-style:italic;padding:8px 0">Henüz tamamlanmış setup yok.</p>'

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{cname} — Bybit Monitor</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    * {{ box-sizing:border-box; }}
    body {{ background:#0d1117; color:#e6edf3; font-family:system-ui,-apple-system,sans-serif; margin:0; }}
    .panel {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:24px; margin-bottom:20px; }}
    .stitle {{ color:#8b949e; font-size:0.72em; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:16px; }}
    table {{ width:100%; border-collapse:collapse; }}
    .trow:hover {{ background:rgba(255,255,255,0.025); }}
    .tf-btn {{ background:#21262d; border:1px solid #30363d; color:#8b949e; border-radius:6px;
               padding:5px 14px; cursor:pointer; font-size:0.82em; transition:all 0.15s; }}
    .tf-btn.active {{ background:#1d4ed8; border-color:#3b82f6; color:#fff; }}
    .tf-btn:hover:not(.active) {{ border-color:#58a6ff; color:#58a6ff; }}
  </style>
</head>
<body style="min-height:100vh;padding:24px;max-width:1200px;margin:0 auto">

  <!-- HEADER -->
  <div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;padding-bottom:20px;border-bottom:1px solid #21262d;flex-wrap:wrap">
    <a href="../index.html" style="color:#64748b;text-decoration:none;font-size:0.85em;white-space:nowrap">&#8592; Dashboard</a>
    <h1 style="flex:1;font-size:1.8em;font-weight:800;color:#e6edf3;margin:0">
      {cname}<span style="font-size:0.5em;color:#64748b;font-weight:400;margin-left:6px">USDT</span>
    </h1>
    <div style="text-align:right">
      <div id="live-price" style="font-size:1.4em;font-weight:700;color:#e6edf3;font-family:monospace">{escape(fmt_price(sym, price))}</div>
      <div style="color:{chg_col};font-size:0.85em;font-weight:600">{escape(chg_str)} (24h)</div>
    </div>
    <button onclick="window.location.reload()" style="background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:8px;padding:8px 14px;cursor:pointer;font-size:0.82em">&#8635; Yenile</button>
  </div>

  <!-- STATS BAR -->
  <div class="panel" style="padding:16px 24px;margin-bottom:20px">
    <div style="display:flex;gap:28px;flex-wrap:wrap;align-items:center">
      <div>
        <div class="stitle" style="margin-bottom:4px">EMA50</div>
        <div style="font-family:monospace;color:#e6edf3">{escape(fmt_price(sym, ema50))}
          <span style="color:{'#10b981' if ema_pct>=0 else '#ef4444'};font-size:0.82em;margin-left:6px">{ema_pct:+.2f}%</span>
        </div>
      </div>
      <div>
        <div class="stitle" style="margin-bottom:4px">RSI(14)</div>
        <div style="font-weight:700;color:{'#ef4444' if rsi14>70 else '#10b981' if rsi14<30 else '#e6edf3'}">{rsi14:.1f}</div>
      </div>
      <div>
        <div class="stitle" style="margin-bottom:4px">Volume</div>
        <div style="color:#e6edf3">{escape(vol)}</div>
      </div>
      <div>
        <div class="stitle" style="margin-bottom:4px">Biases</div>
        <div style="font-size:0.85em;color:#e6edf3">15m: {escape(tf_b.get("15m","—"))} &nbsp; 1h: {escape(tf_b.get("1h","—"))} &nbsp; 4h: {escape(tf_b.get("4h","—"))}</div>
      </div>
      <div>
        <div class="stitle" style="margin-bottom:4px">Consensus</div>
        <span style="background:{cons_col}22;color:{cons_col};border:1px solid {cons_col}55;padding:3px 10px;border-radius:999px;font-size:0.78em;font-weight:600">{escape(cons)}</span>
      </div>
    </div>
  </div>

  <!-- CHART -->
  <div class="panel">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div class="stitle" style="margin-bottom:0">Mum Grafiği</div>
      <div style="display:flex;gap:8px">
        <button class="tf-btn active" onclick="switchTF('15m',this)">15m</button>
        <button class="tf-btn" onclick="switchTF('1h',this)">1h</button>
        <button class="tf-btn" onclick="switchTF('4h',this)">4h</button>
      </div>
    </div>
    <div id="chart-container" style="height:420px;position:relative"></div>
    <div id="chart-error" style="display:none;color:#ef4444;font-size:0.85em;margin-top:8px"></div>
  </div>

  <!-- ACTIVE SETUPS -->
  <div class="panel">
    <div class="stitle">Aktif Setuplar</div>
    {active_html}
  </div>

  <!-- SETUP GEÇMİŞİ -->
  <div class="panel">
    <div class="stitle">Setup Geçmişi (son 50)</div>
    {closed_html}
  </div>

  <!-- FOOTER -->
  <div style="text-align:center;color:#374151;font-size:0.75em;padding:20px 0">
    <a href="../index.html" style="color:#374151;text-decoration:none">&#8592; Ana Dashboard</a>
  </div>

  <script>
    var SYMBOL   = '{sym}';
    var BASE_URL = 'https://data-api.binance.vision/api/v3/klines';
    var setupData = {sets_json};

    var container = document.getElementById('chart-container');
    var chart = LightweightCharts.createChart(container, {{
      width:  container.clientWidth,
      height: 420,
      layout: {{ background: {{ color: '#0d1117' }}, textColor: '#e5e7eb' }},
      grid:   {{ vertLines: {{ color: '#1f2937' }}, horzLines: {{ color: '#1f2937' }} }},
      rightPriceScale: {{ borderColor: '#374151' }},
      timeScale: {{ borderColor: '#374151', timeVisible: true }},
    }});

    var candleSeries = chart.addCandlestickSeries({{
      upColor:'#10b981', downColor:'#ef4444',
      borderUpColor:'#10b981', borderDownColor:'#ef4444',
      wickUpColor:'#10b981', wickDownColor:'#ef4444',
    }});

    var volumeSeries = chart.addHistogramSeries({{
      priceFormat: {{ type: 'volume' }},
      priceScaleId: 'vol',
    }});
    chart.priceScale('vol').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});

    var priceLines = [];

    function drawSetupLines() {{
      for (var i = 0; i < priceLines.length; i++) {{
        try {{ candleSeries.removePriceLine(priceLines[i]); }} catch(e) {{}}
      }}
      priceLines = [];
      for (var j = 0; j < setupData.length; j++) {{
        var s = setupData[j];
        var isActive = s.status === 'active';
        var lw  = isActive ? 2 : 1;
        var sfx = s.status === 'win' ? ' WIN' : s.status === 'loss' ? ' LOSS' : s.status === 'timeout' ? ' TMOUT' : '';
        var a   = isActive ? 1 : 0.4;
        var cEntry  = 'rgba(251,146,60,'  + a + ')';
        var cStop   = 'rgba(239,68,68,'   + a + ')';
        var cTarget = 'rgba(16,185,129,'  + a + ')';
        priceLines.push(candleSeries.createPriceLine({{ price: s.entry,  color: cEntry,  lineWidth: lw, lineStyle: 0, axisLabelVisible: true, title: 'ENTRY' + sfx }}));
        priceLines.push(candleSeries.createPriceLine({{ price: s.stop,   color: cStop,   lineWidth: lw, lineStyle: 2, axisLabelVisible: true, title: 'SL'    + sfx }}));
        priceLines.push(candleSeries.createPriceLine({{ price: s.target, color: cTarget, lineWidth: lw, lineStyle: 2, axisLabelVisible: true, title: 'TP'    + sfx }}));
      }}
    }}

    function fetchAndRender(interval) {{
      document.getElementById('chart-error').style.display = 'none';
      fetch(BASE_URL + '?symbol=' + SYMBOL + '&interval=' + interval + '&limit=100')
        .then(function(resp) {{
          if (!resp.ok) throw new Error('HTTP ' + resp.status);
          return resp.json();
        }})
        .then(function(data) {{
          var candles = data.map(function(k) {{ return {{ time: k[0]/1000, open: +k[1], high: +k[2], low: +k[3], close: +k[4] }}; }});
          var volumes = data.map(function(k) {{ return {{ time: k[0]/1000, value: +k[5], color: +k[4] >= +k[1] ? 'rgba(16,185,129,0.35)' : 'rgba(239,68,68,0.35)' }}; }});
          candleSeries.setData(candles);
          volumeSeries.setData(volumes);
          chart.timeScale().fitContent();
          drawSetupLines();
          var last = candles[candles.length - 1];
          if (last) document.getElementById('live-price').textContent = '$' + last.close.toLocaleString(undefined, {{minimumFractionDigits:2, maximumFractionDigits:6}});
        }})
        .catch(function(e) {{
          var errEl = document.getElementById('chart-error');
          errEl.style.display = 'block';
          errEl.textContent = 'Veri yuklenemedi: ' + e.message;
        }});
    }}

    function switchTF(interval, btn) {{
      document.querySelectorAll('.tf-btn').forEach(function(b) {{ b.classList.remove('active'); }});
      btn.classList.add('active');
      fetchAndRender(interval);
    }}

    window.addEventListener('resize', function() {{ chart.applyOptions({{ width: container.clientWidth }}); }});
    fetchAndRender('15m');
  </script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

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
        if not sym: continue
        try:
            ts = parse_ts(r["timestamp"])
            if sym not in latest or ts > parse_ts(latest[sym]["timestamp"]):
                latest[sym] = r
        except: pass

    now_ts     = max(parse_ts(r["timestamp"]) for r in latest.values()) if latest else datetime.now(TZ_LOCAL)
    now_utc    = datetime.now(timezone.utc)
    update_str = now_ts.astimezone(TZ_LOCAL).strftime("%Y-%m-%d %H:%M UTC+3")

    # ── 24h price changes ─────────────────────────────────────────────────────
    target_24h  = now_ts - timedelta(hours=24)
    changes_24h = {}
    for sym in ALL_SYMBOLS:
        sym_recs = [r for r in decisions if r.get("symbol") == sym]
        if len(sym_recs) < 2: continue
        old_rec = min(sym_recs, key=lambda r: abs((parse_ts(r["timestamp"]) - target_24h).total_seconds()))
        p_old = old_rec.get("price", 0)
        p_new = latest.get(sym, {}).get("price", 0)
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
    wins      = sum(1 for s in setups if s.get("status") == "win")
    losses    = sum(1 for s in setups if s.get("status") == "loss")
    timeouts  = sum(1 for s in setups if s.get("status") == "timeout")
    closed    = wins + losses + timeouts
    net_rr    = round(sum(s["actual_rr"] for s in setups
                          if s.get("status") != "active" and s.get("actual_rr") is not None), 2)
    cutoff7   = now_utc - timedelta(days=7)
    r7        = [s for s in setups if parse_ts(s["timestamp"]).astimezone(timezone.utc) >= cutoff7]
    w7        = sum(1 for s in r7 if s.get("status") == "win")
    c7        = sum(1 for s in r7 if s.get("status") in ("win", "loss", "timeout"))
    wr7_str   = f"%{int(w7/c7*100)} ({w7}/{c7})" if c7 > 0 else "—"

    # ── Sparkline data — all 20 coins ─────────────────────────────────────────
    cutoff_24h    = now_ts - timedelta(hours=24)
    sparkline_data = {}
    for sym in ALL_SYMBOLS:
        sym_recs = sorted([r for r in decisions if r.get("symbol") == sym],
                          key=lambda r: parse_ts(r["timestamp"]))
        recent = [r for r in sym_recs if parse_ts(r["timestamp"]) >= cutoff_24h]
        pct = changes_24h.get(sym)
        is_winner = pct is not None and pct > 0
        if len(recent) >= 2:
            sparkline_data[sym] = {
                "labels": [parse_ts(r["timestamp"]).astimezone(TZ_LOCAL).strftime("%H:%M") for r in recent],
                "prices": [round(r.get("price", 0), 6) for r in recent],
                "isWinner": is_winner,
            }

    def mini_card(sym, delay):
        pct       = changes_24h.get(sym)
        is_winner = pct is not None and pct > 0
        border_col = "#10b981" if is_winner else ("#ef4444" if pct is not None and pct < 0 else "#30363d")
        pct_col    = "#10b981" if is_winner else ("#ef4444" if pct is not None and pct < 0 else "#64748b")
        pct_str    = f"{pct:+.1f}%" if pct is not None else "—"
        has_spark  = sym in sparkline_data
        expand_btn = (
            f'<button onclick="openModal(\'{sym}\')" title="Büyüt" '
            f'style="position:absolute;top:4px;right:4px;background:none;border:none;'
            f'color:#374151;cursor:pointer;padding:1px;line-height:1">'
            f'<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">'
            f'<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>'
            f'</svg></button>' if has_spark else ""
        )
        spark_div = (f'<div style="height:30px;position:relative;margin-top:4px">'
                     f'<canvas id="spark-{sym}"></canvas></div>'
                     if has_spark else
                     '<div style="height:30px;display:flex;align-items:center;justify-content:center;'
                     'color:#1e2530;font-size:0.6em;margin-top:4px">—</div>')
        return (f'<div class="card-hover fade-in" '
                f'style="height:80px;overflow:hidden;background:#161b22;border:1px solid #21262d;'
                f'border-left:3px solid {border_col};border-radius:6px;padding:6px 8px;'
                f'animation-delay:{delay:.2f}s;position:relative;cursor:default">'
                f'{expand_btn}'
                f'<div style="display:flex;justify-content:space-between;align-items:baseline;padding-right:{12 if has_spark else 0}px">'
                f'<span style="font-weight:700;color:#e6edf3;font-size:0.78em">{coin(sym)}</span>'
                f'<span style="color:{pct_col};font-size:0.72em;font-weight:600">{pct_str}</span>'
                f'</div>{spark_div}</div>')

    mover_cards = ""
    for i, sym in enumerate(ALL_SYMBOLS):
        mover_cards += mini_card(sym, i * 0.02)

    # ── Bias flip timeline (last 48h) ─────────────────────────────────────────
    cutoff_48h  = now_ts - timedelta(hours=48)
    flip_events = []
    for sym in ALL_SYMBOLS:
        sym_recs = sorted([r for r in decisions if r.get("symbol") == sym],
                          key=lambda r: parse_ts(r["timestamp"]))
        for i in range(1, len(sym_recs)):
            old_c = sym_recs[i-1].get("consensus", "MIXED")
            new_c = sym_recs[i].get("consensus", "MIXED")
            if old_c != new_c:
                ts = parse_ts(sym_recs[i]["timestamp"])
                if ts >= cutoff_48h:
                    flip_events.append({"ts": ts, "sym": sym, "old": old_c, "new": new_c})
    flip_events.sort(key=lambda x: x["ts"], reverse=True)
    flip_events = flip_events[:20]

    flip_html = ""
    if flip_events:
        for i, ev in enumerate(flip_events):
            ts_l  = ev["ts"].astimezone(TZ_LOCAL).strftime("%d.%m %H:%M")
            col, arrow = flip_direction(ev["old"], ev["new"])
            old_s = ev["old"].replace("STRONG ", "S.")
            new_s = ev["new"].replace("STRONG ", "S.")
            delay = i * 0.04
            flip_html += (f'<div class="fade-in" style="display:flex;align-items:center;gap:10px;'
                          f'padding:7px 0;border-bottom:1px solid #1e2530;animation-delay:{delay:.2f}s">'
                          f'<span style="color:#4b5563;font-size:0.7em;white-space:nowrap;min-width:72px">{ts_l}</span>'
                          f'<span style="color:{col};font-weight:700;font-size:1.1em">{arrow}</span>'
                          f'<span style="color:#c9d1d9;font-weight:700;font-size:0.85em">{coin(ev["sym"])}</span>'
                          f'<span style="color:#4b5563;font-size:0.75em">{escape(old_s)}'
                          f' → <span style="color:{col}">{escape(new_s)}</span></span></div>')
    else:
        flip_html = '<p style="color:#374151;font-style:italic;padding:8px 0">Son 48 saatte flip yok.</p>'

    # ── Category heatmap ─────────────────────────────────────────────────────
    hm_header = "".join(
        f'<th style="color:{c};font-size:0.7em;padding:4px 8px;font-weight:600;text-align:center">{lb}</th>'
        for lb, c in zip(HEATMAP_LABELS, HEATMAP_COLORS)
    )
    hm_rows = ""
    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        counts = {col: 0 for col in HEATMAP_COLS}
        for sym in symbols:
            if sym in latest:
                c = latest[sym].get("consensus", "MIXED")
                if c in counts: counts[c] += 1
        cells = "".join(heatmap_cell_visual(counts[col], col) for col in HEATMAP_COLS)
        hm_rows += (f'<tr><td style="color:#8b949e;font-size:0.78em;padding:6px 10px 6px 0;'
                    f'white-space:nowrap">{escape(cat)}</td>{cells}</tr>\n')

    legend_html = "".join(
        f'<span style="display:flex;align-items:center;gap:4px;font-size:0.68em;color:{c}">'
        f'<span style="width:10px;height:10px;background:{c};border-radius:2px;display:inline-block"></span>{lb}</span>'
        for lb, c in zip(HEATMAP_LABELS, HEATMAP_COLORS)
    )

    # ── Coin table rows ───────────────────────────────────────────────────────
    coin_rows = ""
    for cat, symbols in WATCHLIST_BY_CATEGORY.items():
        for sym in symbols:
            if sym not in latest: continue
            r     = latest[sym]
            price = r.get("price", 0)
            ema50 = r.get("ema50", 0)
            e_pct = (price - ema50) / ema50 * 100 if ema50 > 0 else 0
            rsi   = r.get("rsi14", 0)
            tf    = r.get("tf_biases", {})
            cons  = r.get("consensus", "MIXED")
            vol   = r.get("volume_signal", "")
            chg   = changes_24h.get(sym)
            rc    = "#ef4444" if rsi > 70 else ("#10b981" if rsi < 30 else "#c9d1d9")
            rfw   = "700" if (rsi > 70 or rsi < 30) else "400"
            chg_h = pct_html(chg) if chg is not None else '<span style="color:#374151">—</span>'
            coin_rows += (
                f'<tr class="trow"><td style="padding:10px 12px;white-space:nowrap">'
                f'<a href="coin/{sym}.html" style="font-weight:700;color:#e6edf3;text-decoration:none;transition:color 0.15s"'
                f' onmouseover="this.style.color=\'#58a6ff\'" onmouseout="this.style.color=\'#e6edf3\'">{coin(sym)}</a>'
                f'<span style="color:#374151;font-size:0.7em;margin-left:6px">{escape(cat)}</span></td>'
                f'<td style="padding:10px 12px;font-family:monospace;color:#c9d1d9">{escape(fmt_price(sym, price))}</td>'
                f'<td style="padding:10px 12px">{pct_html(e_pct)}</td>'
                f'<td style="padding:10px 12px;color:{rc};font-weight:{rfw}">{rsi:.1f}</td>'
                f'<td style="text-align:center;padding:10px 8px">{bias_badge(tf.get("15m",""))}</td>'
                f'<td style="text-align:center;padding:10px 8px">{bias_badge(tf.get("1h",""))}</td>'
                f'<td style="text-align:center;padding:10px 8px">{bias_badge(tf.get("4h",""))}</td>'
                f'<td style="padding:10px 12px">{consensus_badge(cons)}</td>'
                f'<td style="padding:10px 12px">{vol_badge(vol)}</td>'
                f'<td style="padding:10px 12px">{chg_h}</td></tr>'
            )

    # ── Active setups ─────────────────────────────────────────────────────────
    if active_setups:
        srows = ""
        for s in active_setups:
            age_h = int((now_utc - parse_ts(s["timestamp"]).astimezone(timezone.utc)).total_seconds() / 3600)
            dc = "#10b981" if s["direction"] == "LONG" else "#ef4444"
            srows += (f'<tr class="trow"><td style="padding:10px 12px;font-weight:700">{coin(s["symbol"])}</td>'
                      f'<td style="padding:10px 12px;color:{dc};font-weight:600">{s["direction"]}</td>'
                      f'<td style="padding:10px 12px;font-family:monospace">{s["entry"]}</td>'
                      f'<td style="padding:10px 12px;font-family:monospace;color:#ef4444">{s["stop"]}</td>'
                      f'<td style="padding:10px 12px;font-family:monospace;color:#10b981">{s["target"]}</td>'
                      f'<td style="padding:10px 12px;color:#f59e0b;font-weight:600">{s["rr_planned"]}:1</td>'
                      f'<td style="padding:10px 12px;color:#64748b">{age_h}s önce</td></tr>')
        th = "".join(f'<th style="text-align:left;padding:8px 12px;color:#64748b;font-size:0.72em">{h}</th>'
                     for h in ["SYM", "DIR", "ENTRY", "STOP", "TARGET", "R:R", "AGE"])
        setup_html = f'<table><thead><tr style="border-bottom:1px solid #30363d">{th}</tr></thead><tbody>{srows}</tbody></table>'
    else:
        setup_html = '<p style="color:#374151;font-style:italic;padding:8px 0">Şu an aktif setup yok.</p>'

    # ── Performance + doughnut ────────────────────────────────────────────────
    doughnut_json = json.dumps({
        "total": len(setups), "wins": wins, "losses": losses,
        "timeouts": timeouts, "active": len(active_setups)
    })
    if setups:
        net_col = "#10b981" if net_rr >= 0 else "#ef4444"
        wr_all  = f"%{int(wins/closed*100)} ({wins}/{closed})" if closed > 0 else "—"
        stats   = [("TOPLAM", str(len(setups)), "#8b949e"), ("AKTİF", str(len(active_setups)), "#3b82f6"),
                   ("WIN", str(wins), "#10b981"), ("LOSS", str(losses), "#ef4444"),
                   ("W.RATE", wr_all, "#f59e0b"), ("NET R", f"{net_rr:+.2f}R", net_col)]
        stat_bl = "".join(
            f'<div style="text-align:center"><div style="color:#64748b;font-size:0.68em;font-weight:600;'
            f'text-transform:uppercase;margin-bottom:4px">{k}</div>'
            f'<div style="font-size:1.25em;font-weight:700;color:{c}">{escape(v)}</div></div>'
            for k, v, c in stats
        )
        perf_html = (f'<div style="display:grid;grid-template-columns:180px 1fr;gap:24px;align-items:center">'
                     f'<div style="height:170px;position:relative"><canvas id="perf-doughnut"></canvas></div>'
                     f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">{stat_bl}</div>'
                     f'</div>')
    else:
        perf_html = '<p style="color:#374151;font-style:italic">Henüz setup verisi yok. İlk setup tetiklendiğinde grafik burada görünecek.</p>'

    # ── Chart JS ──────────────────────────────────────────────────────────────
    spark_json = json.dumps(sparkline_data)
    chart_js   = f"""
    // Sparklines
    const sparkData = {spark_json};
    Object.entries(sparkData).forEach(([sym, d]) => {{
      const el = document.getElementById('spark-' + sym);
      if (!el) return;
      const col = d.isWinner ? '#10b981' : '#ef4444';
      new Chart(el, {{
        type: 'line',
        data: {{
          labels: d.labels,
          datasets: [{{ data: d.prices, borderColor: col, borderWidth: 1.5,
                        pointRadius: 0, fill: true, backgroundColor: col + '18', tension: 0.4 }}]
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }},
          scales: {{ x: {{ display: false }}, y: {{ display: false }} }},
          animation: {{ duration: 800 }}
        }}
      }});
    }});

    // Modal
    let modalChart = null;
    function openModal(sym) {{
      const d = sparkData[sym]; if (!d) return;
      document.getElementById('chart-modal').style.display = 'flex';
      document.getElementById('modal-sym').textContent = sym.replace('USDT','') + ' — 24h Fiyat';
      if (modalChart) {{ modalChart.destroy(); modalChart = null; }}
      const col = d.isWinner ? '#10b981' : '#ef4444';
      modalChart = new Chart(document.getElementById('modal-canvas'), {{
        type: 'line',
        data: {{
          labels: d.labels,
          datasets: [{{ data: d.prices, borderColor: col, borderWidth: 2,
                        pointRadius: 0, fill: true, backgroundColor: col + '18', tension: 0.4 }}]
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          plugins: {{
            legend: {{ display: false }},
            tooltip: {{
              mode: 'index', intersect: false,
              backgroundColor: '#1e2530', borderColor: '#30363d', borderWidth: 1,
              titleColor: '#8b949e', bodyColor: '#e6edf3'
            }}
          }},
          scales: {{
            x: {{ ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, grid: {{ color: '#1e2530' }} }},
            y: {{ ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, grid: {{ color: '#1e2530' }} }}
          }},
          animation: {{ duration: 400 }}
        }}
      }});
    }}
    function closeModal() {{
      document.getElementById('chart-modal').style.display = 'none';
      if (modalChart) {{ modalChart.destroy(); modalChart = null; }}
    }}
    document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});

    // Doughnut
    const dData = {doughnut_json};
    if (dData.total > 0) {{
      const dc = document.getElementById('perf-doughnut');
      if (dc) {{
        new Chart(dc, {{
          type: 'doughnut',
          data: {{
            labels: ['Win', 'Loss', 'Timeout', 'Aktif'],
            datasets: [{{
              data: [dData.wins, dData.losses, dData.timeouts, dData.active],
              backgroundColor: ['#10b981', '#ef4444', '#64748b', '#3b82f6'],
              borderWidth: 0, borderRadius: 3
            }}]
          }},
          options: {{
            responsive: true, maintainAspectRatio: false, cutout: '62%',
            plugins: {{
              legend: {{ position: 'bottom',
                         labels: {{ color: '#8b949e', font: {{ size: 10 }}, padding: 12, boxWidth: 10 }} }}
            }}
          }}
        }});
      }}
    }}
    """

    # ── Table headers helper ──────────────────────────────────────────────────
    def th(headers):
        return "".join(
            f'<th style="text-align:{"center" if h in ["15m","1h","4h"] else "left"};'
            f'padding:8px 12px;color:#64748b;font-size:0.72em">{h}</th>'
            for h in headers
        )

    # ── HTML ──────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <meta http-equiv="refresh" content="3600">
  <title>Bybit Trading Monitor</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * {{ box-sizing:border-box; }}
    body {{ background:#0d1117; color:#e6edf3; font-family:system-ui,-apple-system,sans-serif; margin:0; }}
    .panel {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:24px; margin-bottom:20px; }}
    .stitle {{ color:#8b949e; font-size:0.72em; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:16px; }}
    table {{ width:100%; border-collapse:collapse; }}
    .trow:hover {{ background:rgba(255,255,255,0.025); }}
    .card-hover {{ transition:transform 0.2s ease, box-shadow 0.2s ease; }}
    .card-hover:hover {{ transform:translateY(-2px); box-shadow:0 8px 24px rgba(0,0,0,0.4); }}
    @keyframes fadeInUp {{ from {{ opacity:0; transform:translateY(14px); }} to {{ opacity:1; transform:translateY(0); }} }}
    .fade-in {{ animation:fadeInUp 0.4s ease forwards; opacity:0; }}
    ::-webkit-scrollbar {{ height:4px; width:4px; }}
    ::-webkit-scrollbar-thumb {{ background:#30363d; border-radius:2px; }}
  </style>
</head>
<body style="min-height:100vh;padding:24px;max-width:1200px;margin:0 auto">

  <!-- HEADER -->
  <div class="fade-in" style="margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid #21262d">
    <h1 style="font-size:1.4em;font-weight:700;color:#e6edf3;margin:0 0 4px">Bybit Trading Monitor</h1>
    <p style="color:#64748b;font-size:0.85em;margin:0">Live Dashboard &middot; {escape(update_str)}</p>
  </div>

  <!-- SUMMARY CARDS -->
  <div class="fade-in" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:20px;animation-delay:0.05s">
    <div class="card-hover" style="background:#10b98118;border:1px solid #10b98144;border-radius:10px;padding:18px 20px">
      <div style="color:#10b981;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:6px">Bullish</div>
      <div style="color:#e6edf3;font-size:2em;font-weight:700">{total_bull}</div>
    </div>
    <div class="card-hover" style="background:#ef444418;border:1px solid #ef444444;border-radius:10px;padding:18px 20px">
      <div style="color:#ef4444;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:6px">Bearish</div>
      <div style="color:#e6edf3;font-size:2em;font-weight:700">{total_bear}</div>
    </div>
    <div class="card-hover" style="background:#64748b18;border:1px solid #64748b44;border-radius:10px;padding:18px 20px">
      <div style="color:#64748b;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:6px">Neutral/Mixed</div>
      <div style="color:#e6edf3;font-size:2em;font-weight:700">{total_neut}</div>
    </div>
    <div class="card-hover" style="background:#f59e0b18;border:1px solid #f59e0b44;border-radius:10px;padding:18px 20px">
      <div style="color:#f59e0b;font-size:0.72em;font-weight:600;text-transform:uppercase;margin-bottom:6px">Win Rate 7d</div>
      <div style="color:#e6edf3;font-size:1.5em;font-weight:700">{escape(wr7_str)}</div>
    </div>
  </div>

  <!-- WATCHLIST OVERVIEW -->
  <div class="panel fade-in" style="animation-delay:0.1s">
    <div class="stitle">Watchlist Overview (24h sparklines)</div>
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
      {mover_cards}
    </div>
  </div>

  <!-- HEATMAP + FLIP TIMELINE -->
  <div class="fade-in" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;animation-delay:0.15s">

    <div class="panel" style="margin-bottom:0;overflow-x:auto">
      <div class="stitle">Kategori Heatmap</div>
      <table>
        <thead><tr>
          <th style="text-align:left;padding:4px 0;width:80px"></th>
          {hm_header}
        </tr></thead>
        <tbody>{hm_rows}</tbody>
      </table>
      <div style="display:flex;gap:12px;margin-top:14px;flex-wrap:wrap">{legend_html}</div>
    </div>

    <div class="panel" style="margin-bottom:0;overflow-y:auto;max-height:300px">
      <div class="stitle">Bias Flip Timeline (48h)</div>
      {flip_html}
    </div>

  </div>

  <!-- COIN TABLE -->
  <div class="panel fade-in" style="overflow-x:auto;animation-delay:0.2s">
    <div class="stitle">Coin Durumu</div>
    <table>
      <thead>
        <tr style="border-bottom:1px solid #21262d">
          {th(["SYMBOL","PRICE","EMA%","RSI","15m","1h","4h","CONSENSUS","VOL","24h%"])}
        </tr>
      </thead>
      <tbody>{coin_rows}</tbody>
    </table>
  </div>

  <!-- ACTIVE SETUPS -->
  <div class="panel fade-in" style="overflow-x:auto;animation-delay:0.25s">
    <div class="stitle">Aktif Setuplar ({len(active_setups)})</div>
    {setup_html}
  </div>

  <!-- PERFORMANCE -->
  <div class="panel fade-in" style="animation-delay:0.3s">
    <div class="stitle">Performans Özeti</div>
    {perf_html}
  </div>

  <!-- CHART MODAL -->
  <div id="chart-modal" onclick="closeModal()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:1000;align-items:center;justify-content:center;padding:20px">
    <div onclick="event.stopPropagation()" style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:24px;width:min(820px,95vw);position:relative">
      <button onclick="closeModal()" style="position:absolute;top:12px;right:14px;background:none;border:none;color:#8b949e;font-size:1.4em;cursor:pointer;line-height:1">&#x00D7;</button>
      <div id="modal-sym" style="font-size:1em;font-weight:700;color:#e6edf3;margin-bottom:16px"></div>
      <div style="height:340px;position:relative"><canvas id="modal-canvas"></canvas></div>
    </div>
  </div>

  <!-- FOOTER -->
  <div style="text-align:center;color:#374151;font-size:0.75em;padding:20px 0">
    Auto-generated by GitHub Actions &middot; Updated hourly
  </div>

  <script>
    {chart_js}
  </script>
</body>
</html>"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[build_dashboard] docs/index.html yazıldı ({len(html):,} karakter)")

    # ── Coin detail pages ─────────────────────────────────────────────────────
    coin_dir = os.path.join(os.path.dirname(OUTPUT_FILE), "coin")
    os.makedirs(coin_dir, exist_ok=True)
    for sym in ALL_SYMBOLS:
        sym_setups = [s for s in setups if s.get("symbol") == sym]
        page = coin_page_html(sym, latest.get(sym), sym_setups, changes_24h)
        with open(os.path.join(coin_dir, f"{sym}.html"), "w", encoding="utf-8") as f:
            f.write(page)
    print(f"[build_dashboard] {len(ALL_SYMBOLS)} coin detay sayfası yazıldı → docs/coin/")


if __name__ == "__main__":
    main()

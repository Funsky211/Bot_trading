import sys
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
import os
import json
import webbrowser
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

load_dotenv()

# ── Lire les résultats du backtest ────────────────────────────────────────────
try:
    with open("backtest_results.json", encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    print("❌  backtest_results.json introuvable — lance d'abord backtest.py")
    sys.exit(1)

results      = data["results"]
total_return = data["total_return"]
initial_cash = data["initial_cash"]

# ── Fetch SPY ─────────────────────────────────────────────────────────────────
client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

spy_return     = None
spy_chart_data = {}   # date -> normalized value (base 100)

try:
    spy_req    = StockBarsRequest(
        symbol_or_symbols="SPY",
        timeframe=TimeFrame.Day,
        start=datetime.now() - timedelta(days=data["backtest_days"]),
    )
    spy_prices = client.get_stock_bars(spy_req).df.loc["SPY"]["close"]
    spy_return = (spy_prices.iloc[-1] - spy_prices.iloc[0]) / spy_prices.iloc[0] * 100
    spy_first  = spy_prices.iloc[0]
    for d, v in spy_prices.items():
        spy_chart_data[str(d.date())] = round(float(v) / float(spy_first) * 100, 2)
    print(f"  SPY buy-and-hold : {spy_return:+.2f}%")
except Exception as e:
    print(f"  ⚠️  SPY non disponible : {e}")

# ── Courbe d'equity du portefeuille (base 100) ────────────────────────────────
chart_bot_data = {
    date_str: round(equity / initial_cash * 100, 2)
    for date_str, equity in data.get("portfolio_daily", [])
}


# ── Génération HTML ───────────────────────────────────────────────────────────
def _generate_html(results, spy_return, total_return, data, chart_bot_data, spy_chart_data):
    date_str    = datetime.now().strftime("%Y-%m-%d %H:%M")
    gen_date    = data.get("generated", "")[:10]
    final_eq    = data.get("final_equity", initial_cash)
    spy_label   = f"{spy_return:+.2f}%" if spy_return is not None else "N/A"
    spy_delta   = (total_return - spy_return) if spy_return is not None else None
    delta_label = f"{spy_delta:+.2f}%" if spy_delta is not None else "N/A"
    pos         = "#27ae60"
    neg         = "#e74c3c"
    neu         = "#7f8c8d"
    delta_color = pos if (spy_delta or 0) >= 0 else neg

    tp_levels = data.get("take_profit_levels", [])

    # Données graphique
    all_dates    = sorted(set(chart_bot_data) | set(spy_chart_data))
    chart_labels = json.dumps(all_dates)
    chart_bot    = json.dumps([chart_bot_data.get(d) for d in all_dates])
    chart_spy    = json.dumps([spy_chart_data.get(d) for d in all_dates])

    rows = []
    for r in sorted(results, key=lambda x: x["pnl"], reverse=True):
        bh       = r["bh_return"]
        tp_cells = "".join(f'<td class="num">{n}</td>' for n in r["tp_counts"])
        rows.append(f"""<tr>
          <td class="sym">{r["symbol"]}</td>
          <td class="num" style="color:{pos if r['pnl']>=0 else neg};font-weight:700">{r["pnl"]:+,.0f}$</td>
          <td class="num" style="color:{pos if bh>=0 else neg}">{bh:+.2f}%</td>
          <td class="num">{r["trades"]}</td>
          <td class="num">{r["win_rate"]:.0f}%</td>
          <td class="num">{r["sl_count"]}</td>
          {tp_cells}
        </tr>""")

    tp_headers = "".join(
        f'<th onclick="sort({6 + i})" title="Palier TP{i+1}">'
        f'TP{i+1} <small>(+{tp_pct*100:.0f}%)</small></th>'
        for i, (tp_pct, _) in enumerate(tp_levels)
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Rapport Backtest — Portefeuille vs S&P500</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
        background:#f0f2f5;color:#2c3e50;padding:28px}}
  h1{{font-size:1.55rem;font-weight:700;margin-bottom:4px}}
  h2{{font-size:1.1rem;font-weight:600;margin:28px 0 12px}}
  .sub{{color:#7f8c8d;font-size:.88rem;margin-bottom:24px}}
  .cards{{display:flex;gap:14px;margin-bottom:26px;flex-wrap:wrap}}
  .card{{background:#fff;border-radius:12px;padding:16px 22px;min-width:155px;
          box-shadow:0 1px 6px rgba(0,0,0,.08)}}
  .card .lbl{{font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;
               color:#95a5a6;margin-bottom:5px}}
  .card .val{{font-size:1.45rem;font-weight:700}}
  .chart-box{{background:#fff;border-radius:12px;padding:20px 24px;
               box-shadow:0 1px 6px rgba(0,0,0,.08);margin-bottom:26px}}
  .wrap{{background:#fff;border-radius:12px;overflow:hidden;
          box-shadow:0 1px 6px rgba(0,0,0,.08)}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#2c3e50;color:#fff;padding:10px 13px;font-size:.75rem;
             text-transform:uppercase;letter-spacing:.05em;
             cursor:pointer;user-select:none;white-space:nowrap}}
  thead th:hover{{background:#3d5166}}
  td{{padding:9px 13px;border-bottom:1px solid #edf0f2;font-size:.88rem}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:#fafbfc}}
  td.sym{{font-weight:600;letter-spacing:.02em}}
  td.num{{text-align:right}}
  th{{text-align:right}}
  th:first-child{{text-align:left}}
  .badge{{display:inline-block;background:#eaf0fb;color:#2c6fcc;
           border-radius:6px;padding:2px 9px;font-size:.75rem;font-weight:600;
           margin-left:10px;vertical-align:middle}}
  footer{{margin-top:18px;color:#aab0b8;font-size:.78rem;text-align:right}}
</style>
</head>
<body>

<h1>Rapport Backtest <span class="badge">Généré le {date_str}</span></h1>
<p class="sub">
  Backtest du {gen_date} &nbsp;·&nbsp;
  {data["backtest_days"]} jours &nbsp;·&nbsp;
  {len(results)} actions &nbsp;·&nbsp;
  Capital ${initial_cash:,.0f} (pool partagé) &nbsp;·&nbsp;
  {data.get("buy_pct", 0)*100:.0f}%/position &nbsp;·&nbsp;
  Stratégies <strong>{data.get("strategies", "Trend Following + Mean Reversion")}</strong> &nbsp;·&nbsp;
  SL {data["stop_loss_pct"]*100:.0f}%
</p>

<div class="cards">
  <div class="card">
    <div class="lbl">Portefeuille — rendement</div>
    <div class="val" style="color:{pos if total_return>=0 else neg}">{total_return:+.2f}%</div>
  </div>
  <div class="card">
    <div class="lbl">Equity finale</div>
    <div class="val">${final_eq:,.0f}</div>
  </div>
  <div class="card">
    <div class="lbl">SPY buy-and-hold</div>
    <div class="val" style="color:{neu}">{spy_label}</div>
  </div>
  <div class="card">
    <div class="lbl">Δ Portefeuille vs SPY</div>
    <div class="val" style="color:{delta_color}">{delta_label}</div>
  </div>
</div>

<h2>Performance dans le temps (base 100)</h2>
<div class="chart-box">
  <canvas id="perfChart" height="80"></canvas>
</div>

<h2>Détail par action (contribution au portefeuille)</h2>
<div class="wrap">
<table id="t">
  <thead><tr>
    <th onclick="sort(0)" style="text-align:left">Symbole</th>
    <th onclick="sort(1)">PnL $</th>
    <th onclick="sort(2)">Buy&amp;Hold %</th>
    <th onclick="sort(3)">Trades</th>
    <th onclick="sort(4)">Win rate</th>
    <th onclick="sort(5)">SL</th>
    {tp_headers}
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>

<footer>Données issues de backtest_results.json — {gen_date}</footer>

<script>
// ── Graphique performance ──────────────────────────────────────────────────
new Chart(document.getElementById('perfChart'), {{
  type: 'line',
  data: {{
    labels: {chart_labels},
    datasets: [
      {{
        label: 'Portefeuille',
        data: {chart_bot},
        borderColor: '#27ae60',
        backgroundColor: 'rgba(39,174,96,.07)',
        fill: true,
        tension: 0.2,
        pointRadius: 0,
        borderWidth: 2,
        spanGaps: true,
      }},
      {{
        label: 'SPY (S&P500)',
        data: {chart_spy},
        borderColor: '#2980b9',
        backgroundColor: 'rgba(41,128,185,.05)',
        fill: true,
        tension: 0.2,
        pointRadius: 0,
        borderWidth: 2,
        spanGaps: true,
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'top' }},
      tooltip: {{
        callbacks: {{
          label: ctx => ` ${{ctx.dataset.label}}: ${{ctx.parsed.y?.toFixed(1) ?? 'N/A'}}`
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ maxTicksLimit: 14, maxRotation: 0 }},
        grid: {{ display: false }}
      }},
      y: {{
        title: {{ display: true, text: 'Valeur normalisée (base 100)' }},
        ticks: {{ callback: v => v.toFixed(0) }}
      }}
    }}
  }}
}});

// ── Tri tableau ───────────────────────────────────────────────────────────
let _col = -1, _asc = false;
function sort(col) {{
  const tb = document.querySelector("#t tbody");
  const rows = [...tb.rows];
  _asc = _col === col ? !_asc : true;
  _col = col;
  rows.sort((a, b) => {{
    const x = a.cells[col].innerText.replace(/[+%,$]/g, "").trim();
    const y = b.cells[col].innerText.replace(/[+%,$]/g, "").trim();
    const nx = parseFloat(x), ny = parseFloat(y);
    if (!isNaN(nx) && !isNaN(ny)) return _asc ? nx - ny : ny - nx;
    return _asc ? x.localeCompare(y) : y.localeCompare(x);
  }});
  rows.forEach(r => tb.appendChild(r));
}}
</script>
</body>
</html>"""


# ── Écriture et ouverture ─────────────────────────────────────────────────────
html     = _generate_html(results, spy_return, total_return, data, chart_bot_data, spy_chart_data)
out_path = os.path.abspath("backtest_results.html")

with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"  📄 Rapport généré : backtest_results.html")
webbrowser.open(out_path)

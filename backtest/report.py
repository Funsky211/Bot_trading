import sys, os
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
import json
import webbrowser
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Paths : on lit/écrit à côté du script (sous-dossier backtest/).
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT  = os.path.dirname(SCRIPT_DIR)
RESULTS_JSON  = os.path.join(SCRIPT_DIR, "backtest_results.json")
RESULTS_HTML  = os.path.join(SCRIPT_DIR, "backtest_results.html")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ── Lire les résultats du backtest ────────────────────────────────────────────
try:
    with open(RESULTS_JSON, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"❌  {RESULTS_JSON} introuvable — lance d'abord backtest.py")
    sys.exit(1)

results        = data["results"]
total_return   = data["total_return"]
initial_cash   = data["initial_cash"]
final_eq       = data.get("final_equity", initial_cash)
gen_iso        = data.get("generated", "")
gen_date       = gen_iso[:10] if gen_iso else ""

# Champs spécifiques nouvelle version (avec fallback pour ancien JSON)
first_alloc    = data.get("first_allocation")              # ex: "2019-07"
strategies_lbl = data.get("strategies", "Stratégies")
txn_bp         = data.get("transaction_cost_bp", 0)
strat_weights  = data.get("strategy_weights")              # None ou dict/list
total_fees     = data.get("total_fees", 0)
regime_on      = data.get("regime_filter", False)
regime_sma     = data.get("regime_sma_months")
bearish_months = data.get("bearish_months", 0)

portfolio_curve = data.get("portfolio_daily", [])          # list[ [date_str, equity] ]
backtest_days   = data.get("backtest_days", 0)

# ── Date de début / fin pour le SPY (comparaison équitable) ───────────────────
# On veut comparer SPY à la même fenêtre que l'exécution réelle du bot :
# du premier mois d'allocation à la fin du backtest.
if first_alloc:
    # first_alloc = "YYYY-MM" → 1er jour de ce mois
    try:
        spy_start = datetime.strptime(first_alloc + "-01", "%Y-%m-%d")
    except ValueError:
        spy_start = datetime.now() - timedelta(days=backtest_days)
elif portfolio_curve:
    # Fallback : 1ère date de la courbe portefeuille
    try:
        spy_start = datetime.strptime(portfolio_curve[0][0] + "-01", "%Y-%m-%d")
    except ValueError:
        spy_start = datetime.strptime(portfolio_curve[0][0], "%Y-%m-%d")
else:
    spy_start = datetime.now() - timedelta(days=backtest_days)

# ── Fetch SPY pour comparaison ────────────────────────────────────────────────
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
        start=spy_start,
    )
    spy_prices = client.get_stock_bars(spy_req).df.loc["SPY"]["close"]
    # tz strip (Alpaca renvoie UTC) pour éviter warnings ultérieurs
    if spy_prices.index.tz is not None:
        spy_prices.index = spy_prices.index.tz_localize(None)
    spy_return = (spy_prices.iloc[-1] - spy_prices.iloc[0]) / spy_prices.iloc[0] * 100
    spy_first  = spy_prices.iloc[0]
    for d, v in spy_prices.items():
        spy_chart_data[str(d.date())] = round(float(v) / float(spy_first) * 100, 2)
    print(f"  SPY buy-and-hold (depuis {spy_start.date()}) : {spy_return:+.2f}%")
except Exception as e:
    print(f"  ⚠️  SPY non disponible : {e}")

# ── Courbe equity du portefeuille (base 100) ──────────────────────────────────
# Le 1er point de la courbe = INITIAL_CASH (base 100). Les points suivants
# = equity de fin de mois → ratio base 100.
chart_bot_data = {
    date_str: round(equity / initial_cash * 100, 2)
    for date_str, equity in portfolio_curve
}

# ── Compte d'actions effectivement tradées (au moins 1 transaction) ───────────
traded_results = [r for r in results if r.get("trades", 0) > 0]
n_traded       = len(traded_results)

# ── Libellé pondération stratégies ────────────────────────────────────────────
if strat_weights is None:
    strat_w_label = "equal-weight"
elif isinstance(strat_weights, dict):
    strat_w_label = ", ".join(f"{k}:{v:.0%}" for k, v in strat_weights.items())
else:
    strat_w_label = str(strat_weights)


# ── Génération HTML ───────────────────────────────────────────────────────────
def _generate_html():
    now_str     = datetime.now().strftime("%Y-%m-%d %H:%M")
    spy_label   = f"{spy_return:+.2f}%" if spy_return is not None else "N/A"
    spy_delta   = (total_return - spy_return) if spy_return is not None else None
    delta_label = f"{spy_delta:+.2f}%" if spy_delta is not None else "N/A"
    pos         = "#27ae60"
    neg         = "#e74c3c"
    neu         = "#7f8c8d"
    delta_color = pos if (spy_delta or 0) >= 0 else neg

    # Fenêtre d'exécution (en mois) à partir de la courbe portefeuille
    if portfolio_curve:
        first_label = portfolio_curve[0][0]
        last_label  = portfolio_curve[-1][0]
        n_months    = max(0, len(portfolio_curve) - 1)
    else:
        first_label = first_alloc or "?"
        last_label  = "?"
        n_months    = 0

    # Données graphique
    all_dates    = sorted(set(chart_bot_data) | set(spy_chart_data))
    chart_labels = json.dumps(all_dates)
    chart_bot    = json.dumps([chart_bot_data.get(d) for d in all_dates])
    chart_spy    = json.dumps([spy_chart_data.get(d) for d in all_dates])

    rows = []
    for r in sorted(results, key=lambda x: x["pnl"], reverse=True):
        if r.get("trades", 0) == 0:
            continue
        bh = r["bh_return"]
        rows.append(f"""<tr>
          <td class="sym">{r["symbol"]}</td>
          <td class="num" style="color:{pos if r['pnl']>=0 else neg};font-weight:700">{r["pnl"]:+,.0f}$</td>
          <td class="num" style="color:{pos if bh>=0 else neg}">{bh:+.2f}%</td>
          <td class="num">{r["trades"]}</td>
          <td class="num">{r["win_rate"]:.0f}%</td>
        </tr>""")

    fees_line = (f"Frais cumulés ${total_fees:,.0f} &nbsp;·&nbsp; "
                 if total_fees else "")
    if regime_on:
        bull_pct = (n_months - bearish_months) / n_months * 100 if n_months else 0
        regime_line = (f"Filtre régime SPY > MM{regime_sma} mois : "
                       f"<strong>ON</strong> "
                       f"({bearish_months}/{n_months} mois bearish, "
                       f"{bull_pct:.0f}% bullish) &nbsp;·&nbsp; ")
    else:
        regime_line = "Filtre régime : <strong>OFF</strong> &nbsp;·&nbsp; "

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
  .sub{{color:#7f8c8d;font-size:.88rem;margin-bottom:24px;line-height:1.6}}
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

<h1>Rapport Backtest <span class="badge">Généré le {now_str}</span></h1>
<p class="sub">
  Fenêtre d'exécution : <strong>{first_label} → {last_label}</strong> ({n_months} mois) &nbsp;·&nbsp;
  {n_traded} actions tradées &nbsp;·&nbsp;
  Capital initial ${initial_cash:,.0f} &nbsp;·&nbsp;
  Rebalancement mensuel (signal au close fin de mois, exécution à l'open du mois suivant) &nbsp;·&nbsp;
  Frais {txn_bp} bp/jambe ({2*txn_bp} bp aller-retour) &nbsp;·&nbsp;
  {fees_line}{regime_line}Pondération inter-stratégies : <strong>{strat_w_label}</strong> &nbsp;·&nbsp;
  Stratégies : <strong>{strategies_lbl}</strong>
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

<h2>Détail par action ({n_traded} tickers tradés)</h2>
<div class="wrap">
<table id="t">
  <thead><tr>
    <th onclick="sort(0)" style="text-align:left">Symbole</th>
    <th onclick="sort(1)">PnL $</th>
    <th onclick="sort(2)">Buy&amp;Hold %</th>
    <th onclick="sort(3)">Trades</th>
    <th onclick="sort(4)">Win rate</th>
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
html = _generate_html()

with open(RESULTS_HTML, "w", encoding="utf-8") as f:
    f.write(html)

print(f"  📄 Rapport généré : {RESULTS_HTML}")
webbrowser.open(RESULTS_HTML)

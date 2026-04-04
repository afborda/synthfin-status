#!/usr/bin/env python3
"""
Gera o dashboard HTML a partir de tests/e2e/results/latest.json
Publicado no GitHub Pages via gh-pages branch.
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def load_results(path: str = "tests/e2e/results/latest.json") -> dict:
    return json.loads(Path(path).read_text())


def status_badge(rate: float) -> str:
    if rate >= 95:  return ("✅", "#00d4aa", "Passing")
    if rate >= 80:  return ("⚠️", "#fdcb6e", "Degraded")
    return ("❌", "#e17055", "Failing")


def category_color(cat: str) -> str:
    return {
        "infra":  "#6c5ce7",
        "auth":   "#00b894",
        "batch":  "#0984e3",
        "stream": "#00d4aa",
        "ai":     "#e84393",
        "web":    "#fdcb6e",
    }.get(cat, "#888")


def fmt_ms(ms: float) -> str:
    if ms >= 1000: return f"{ms/1000:.1f}s"
    return f"{ms:.0f}ms"


def generate_dashboard(data: dict) -> str:
    s        = data["summary"]
    results  = data["results"]
    run_id   = data["run_id"]
    started  = data["started_at"][:19].replace("T", " ")
    finished = data.get("finished_at", "")[:19].replace("T", " ")
    api_url  = data.get("api_url", "")

    icon, color, label = status_badge(s["pass_rate"])

    # Group by category
    by_cat: dict = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    # Per-category stats
    cat_stats = []
    for cat, tests in by_cat.items():
        passed  = sum(1 for t in tests if t["status"] == "pass")
        total   = sum(1 for t in tests if t["status"] != "skip")
        rate    = round(passed / total * 100, 1) if total > 0 else 0
        avg_ms  = round(sum(t["duration_ms"] for t in tests if t["status"] == "pass") / max(passed, 1), 0)
        cat_stats.append({"cat": cat, "rate": rate, "passed": passed, "total": total, "avg_ms": avg_ms})

    # Build results table rows
    rows_html = ""
    for r in results:
        if r["status"] == "pass":
            status_html = '<span class="badge pass">✓ pass</span>'
        elif r["status"] == "fail":
            status_html = '<span class="badge fail">✗ fail</span>'
        else:
            status_html = '<span class="badge skip">– skip</span>'

        err_html = f'<div class="error">{r["error"]}</div>' if r.get("error") else ""
        cat_c    = category_color(r["category"])
        details  = r.get("details", {})
        detail_str = ""
        if details:
            key_details = {k: v for k, v in details.items() if k != "status" and v is not None}
            if key_details:
                detail_str = f'<div class="detail">{json.dumps(key_details, ensure_ascii=False)[:200]}</div>'

        rows_html += f"""
        <tr class="result-row {r['status']}">
          <td><span class="cat-dot" style="background:{cat_c}"></span> {r['category']}</td>
          <td class="test-name">{r['name']}</td>
          <td>{status_html}</td>
          <td class="duration">{fmt_ms(r['duration_ms'])}</td>
          <td>{r.get('http_status') or '—'}</td>
          <td>{err_html}{detail_str}</td>
        </tr>"""

    # Category bar chart (pure CSS)
    bars_html = ""
    for cs in sorted(cat_stats, key=lambda x: -x["rate"]):
        c = category_color(cs["cat"])
        bars_html += f"""
        <div class="bar-row">
          <div class="bar-label">{cs['cat']}</div>
          <div class="bar-track">
            <div class="bar-fill" style="width:{cs['rate']}%;background:{c}">
              <span class="bar-pct">{cs['rate']}%</span>
            </div>
          </div>
          <div class="bar-meta">{cs['passed']}/{cs['total']} · {fmt_ms(cs['avg_ms'])}</div>
        </div>"""

    # Duration breakdown
    dur_items = sorted(
        [r for r in results if r["status"] == "pass"],
        key=lambda x: -x["duration_ms"],
    )
    dur_max = dur_items[0]["duration_ms"] if dur_items else 1
    dur_html = ""
    for d in dur_items[:10]:
        pct  = (d["duration_ms"] / dur_max) * 100
        slow = "slow" if d["duration_ms"] > 5000 else ("medium" if d["duration_ms"] > 1000 else "")
        dur_html += f"""
        <div class="dur-row">
          <div class="dur-name">{d['name']}</div>
          <div class="dur-track">
            <div class="dur-bar {slow}" style="width:{pct:.1f}%"></div>
          </div>
          <div class="dur-val {slow}">{fmt_ms(d['duration_ms'])}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SynthFin E2E Dashboard — {run_id}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    :root {{
      --bg: #080808; --surface: #0f0f0f; --border: #1a1a1a;
      --text: #e8e8e8; --muted: #888; --accent: #00d4aa;
    }}
    body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; }}
    a {{ color: var(--accent); text-decoration: none; }}

    .header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 20px 32px; display: flex; align-items: center; justify-content: space-between; }}
    .header-left h1 {{ font-size: 18px; font-weight: 800; letter-spacing: -.5px; }}
    .header-left p {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
    .status-badge {{ display: flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: 999px; font-size: 13px; font-weight: 700; border: 1px solid; }}

    .main {{ max-width: 1200px; margin: 0 auto; padding: 32px; }}

    /* KPI cards */
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 32px; }}
    .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; text-align: center; }}
    .kpi-value {{ font-size: 32px; font-weight: 900; line-height: 1; }}
    .kpi-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .8px; margin-top: 6px; }}

    /* 2-col grid */
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 32px; }}
    @media (max-width: 768px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}

    .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 20px; }}
    .card-title {{ font-size: 12px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .8px; margin-bottom: 16px; }}

    /* Bar chart */
    .bar-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
    .bar-label {{ width: 64px; font-size: 12px; color: var(--muted); text-align: right; flex-shrink: 0; }}
    .bar-track {{ flex: 1; height: 20px; background: #111; border-radius: 4px; overflow: hidden; }}
    .bar-fill {{ height: 100%; border-radius: 4px; display: flex; align-items: center; padding-left: 8px; transition: width .6s ease; min-width: 30px; }}
    .bar-pct {{ font-size: 10px; font-weight: 700; color: #000; }}
    .bar-meta {{ width: 100px; font-size: 11px; color: var(--muted); flex-shrink: 0; }}

    /* Duration */
    .dur-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
    .dur-name {{ width: 220px; font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0; }}
    .dur-track {{ flex: 1; height: 8px; background: #111; border-radius: 4px; overflow: hidden; }}
    .dur-bar {{ height: 100%; border-radius: 4px; background: var(--accent); }}
    .dur-bar.medium {{ background: #fdcb6e; }}
    .dur-bar.slow {{ background: #e17055; }}
    .dur-val {{ width: 60px; font-size: 12px; font-weight: 600; text-align: right; flex-shrink: 0; }}
    .dur-val.medium {{ color: #fdcb6e; }}
    .dur-val.slow {{ color: #e17055; }}

    /* Results table */
    .table-wrap {{ overflow-x: auto; margin-top: 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th {{ background: #111; padding: 10px 12px; text-align: left; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .5px; font-size: 10px; border-bottom: 1px solid var(--border); }}
    td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
    tr.pass:hover td {{ background: rgba(0,212,170,.04); }}
    tr.fail td {{ background: rgba(225,112,85,.04); }}
    tr.skip td {{ opacity: .5; }}

    .cat-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }}
    .test-name {{ font-weight: 500; color: var(--text); }}
    .duration {{ font-family: monospace; color: var(--muted); }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; }}
    .badge.pass {{ background: rgba(0,212,170,.15); color: #00d4aa; }}
    .badge.fail {{ background: rgba(225,112,85,.15); color: #e17055; }}
    .badge.skip {{ background: rgba(136,136,136,.15); color: #888; }}
    .error {{ color: #e17055; font-size: 11px; margin-top: 2px; font-family: monospace; }}
    .detail {{ color: var(--muted); font-size: 10px; font-family: monospace; margin-top: 2px; word-break: break-all; }}

    .footer {{ text-align: center; padding: 32px; color: var(--muted); font-size: 11px; border-top: 1px solid var(--border); }}
    .run-meta {{ display: flex; gap: 20px; font-size: 11px; color: var(--muted); margin-bottom: 4px; }}
    .run-meta span {{ display: flex; align-items: center; gap: 4px; }}
  </style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>SynthFin <span style="color:var(--accent)">E2E Dashboard</span></h1>
    <p>Run #{run_id} · {api_url}</p>
  </div>
  <div class="status-badge" style="color:{color};border-color:{color}30;background:{color}15">
    {icon} {label} — {s['pass_rate']}%
  </div>
</div>

<div class="main">

  <!-- Run metadata -->
  <div class="run-meta" style="margin-bottom:24px">
    <span>🕐 Iniciado: {started}</span>
    <span>🕑 Finalizado: {finished}</span>
    <span>⏱ Duração média: {fmt_ms(s['avg_duration_ms'])}</span>
  </div>

  <!-- KPI cards -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-value" style="color:{color}">{s['pass_rate']}%</div>
      <div class="kpi-label">Pass Rate</div>
    </div>
    <div class="kpi">
      <div class="kpi-value" style="color:#00d4aa">{s['passed']}</div>
      <div class="kpi-label">Passed</div>
    </div>
    <div class="kpi">
      <div class="kpi-value" style="color:#e17055">{s['failed']}</div>
      <div class="kpi-label">Failed</div>
    </div>
    <div class="kpi">
      <div class="kpi-value" style="color:#888">{s['skipped']}</div>
      <div class="kpi-label">Skipped</div>
    </div>
    <div class="kpi">
      <div class="kpi-value" style="color:#e8e8e8">{s['total']}</div>
      <div class="kpi-label">Total Tests</div>
    </div>
    <div class="kpi">
      <div class="kpi-value" style="color:#0984e3">{fmt_ms(s['avg_duration_ms'])}</div>
      <div class="kpi-label">Avg Duration</div>
    </div>
  </div>

  <!-- Charts row -->
  <div class="grid-2">

    <div class="card">
      <div class="card-title">Pass Rate por Categoria</div>
      {bars_html}
    </div>

    <div class="card">
      <div class="card-title">Top 10 — Duração (ms)</div>
      {dur_html}
    </div>

  </div>

  <!-- Results table -->
  <div class="card">
    <div class="card-title">Todos os Testes</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Categoria</th>
            <th>Teste</th>
            <th>Status</th>
            <th>Duração</th>
            <th>HTTP</th>
            <th>Detalhes</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
  </div>

</div>

<div class="footer">
  SynthFin E2E Dashboard · Gerado em {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} · Run {run_id}
</div>

</body>
</html>"""


if __name__ == "__main__":
    results_path = sys.argv[1] if len(sys.argv) > 1 else "tests/e2e/results/latest.json"
    output_path  = sys.argv[2] if len(sys.argv) > 2 else "tests/e2e/results/dashboard.html"

    if not Path(results_path).exists():
        print(f"❌ {results_path} not found. Run run_e2e.py first.")
        sys.exit(1)

    data = load_results(results_path)
    html = generate_dashboard(data)
    Path(output_path).write_text(html, encoding="utf-8")
    print(f"✅ Dashboard generated: {output_path}")

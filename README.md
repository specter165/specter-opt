# SPECTER-OPT Paper-Trading Agent

Autonomous, risk-controlled options agent for the **Moomoo x Qoder AI Paper Trading Agent Challenge**.

## Scope

- Universe: **screener-driven**, not a fixed list. Each morning `scripts/build_universe.py` aggregates Moomoo's `quote_option_screen` output by underlying (option volume, open interest, implied volatility), applies hard liquidity/price/IV filters, and ranks the survivors with a deterministic composite score. Default cap is 8 symbols; the selection is cached in `data/universe.json` for 8 hours so intraday scans reuse it instead of re-screening.
  - No symbol is hard-coded. `UniverseConfig.always_include` can anchor symbols (empty by default), and `config.universe` is only the offline/fallback list.
  - Screener-discovered symbols fall into the `single_name` cluster, so combined premium in unlisted names is still capped at 2% of equity.
- Single names carry stricter liquidity gates (OI >= 1000, relative spread <= 3%) and an earnings blackout: no contract whose expiry spans a known earnings date. When no forward earnings date is available the contract life is capped at `unknown_earnings_max_dte` (10 days) instead of blocking the name; `require_earnings_calendar=True` restores the old fail-closed behaviour.
- Correlated-exposure clusters cap combined premium: SPY/QQQ share `index`, QQQ/NVDA/AAPL share `megacap_tech`, so a QQQ position consumes both budgets.
- Pricing: American binomial tree with BSM European reference.
- Forecasting: EWMA + Student-t physical-measure scenarios (M0 zero-drift baseline).
- Selection: hard filters, robust expected net P&L, CVaR, premium sizing.
- Execution: persisted intents, duplicate prevention, reconciliation, limit orders only.
- Risk: per-trade and aggregate premium limits, drawdown halts, no shorts/borrowing/uncovered exposure.

## Status

Current mode: **paper** for the Moomoo x Qoder AI Trading Agent Challenge account `5830137`, authorized until 1 December 2026. The agent runs autonomously via Qoder Forward schedules.

Read next: **[Trading thesis and invalidation](docs/THESIS.md)** — what the edge is, why it
can exist, and the seven pre-committed conditions that disprove it.
**[Agent report](docs/REPORT.md)** — architecture, decision loop, live-run results, and
what we would build next.

## Project layout

```
specter-opt/
  src/specter_opt/       Core modules
  src/specter_opt/agents/ Multi-agent orchestration layer
  tests/                 Unit and integration tests
  scripts/               Runners, dashboard, and schedule helpers
  data/                  Runtime state and snapshots (excluded from git)
  decision-logs/         JSONL audit trail (excluded from git)
```

## Quick start

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
python scripts/run_shadow.py
python scripts/generate_dashboard.py
```

## Required environment variables

Create a `.env` file or export these before running:

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SPECTER_GIT_REMOTE=https://github.com/YOURNAME/specter-opt.git   # for schedule sandboxes
```

Do not commit `.env` files to git.

## Shadow mode

`scripts/run_shadow.py` runs the full pipeline against synthetic SPY/QQQ chains and a mock broker. It produces decision logs and a run result without any broker interaction.

## Paper mode from Moomoo snapshot

1. The assistant collects account, positions, open orders, underlying quotes and option chains via MCP tools and writes them to `data/snapshot.json`.
2. Run:

```bash
python scripts/run_moomoo_paper.py --snapshot data/snapshot.json --mode shadow  # shadow first
SPECTER_MODE=paper python scripts/run_moomoo_paper.py --snapshot data/snapshot.json --mode paper
```

## Scheduling

Use the Qoder Forward scheduler (cron/interval) to trigger the assistant at set times. The assistant then runs MCP queries, executes `run_moomoo_paper.py`, and reports results. Do not enable paper scheduling until all readiness gates pass.

## Risk controls

| Control | Value |
|---|---|
| Per-trade premium + entry cost | 0.5% equity |
| Aggregate open premium | 3% equity |
| Concurrent positions | 3 |
| Daily equity loss block | 2% |
| Peak drawdown halt | 5% |
| Max orders / US trading day | 20 |
| Short options / borrowing / uncovered | Disabled |

## Readiness gates

Before automated paper orders:

1. Verify paper account identity, rules, permissions and single execution ownership.
2. Pass pricing, risk, reconciliation, restart and failure-injection tests.
3. Validate forecasts chronologically.
4. Evaluate executable options economics after costs.
5. Demonstrate complete workflow in shadow mode.
6. Produce a readiness report.

## Pause / shutdown / emergency

- Set environment `SPECTER_MODE=halt` or call `RiskGuard.manual_halt(reason)`.
- Delete/clear `data/risk_state.json` only after understanding it resets baselines.
- For emergency broker-side halt, cancel all open orders via the Moomoo platform.

## License / competition

This is a competition submission artifact. See `docs/` for architecture, assumptions and limitations.

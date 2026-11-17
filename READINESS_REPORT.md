# SPECTER-OPT Readiness Report

Date: 2026-11-17 (UTC)
Agent version: 1.0.0
Operating mode: **paper** (authorized until 1 Dec 2026)

## 1. Account verification

| Check | Result |
|---|---|
| Dedicated competition account located | Yes — `5830137` "Moomoo x Qoder AI Paper Trading Agent Challenge" |
| Simulated/paper status | Yes (`account_type=2`, market_id=100) |
| Current cash/equity | USD 100,000 / 100,000 |
| Existing positions | None |
| Existing open orders | None |
| Competing cloud schedules | 2 active: SPECTER-OPT Daily Paper Run, SPECTER-OPT Paper Auto-Pause |

The account was verified by direct MCP query. No other active schedules or deployments controlling the same account were found.

**MCP access note:** The live/competition account-scope APIs (`account_positions`, `account_orders_active`, `account_funds`) currently return `Unauthorized`. However, the **simulated-trading MCP APIs** for the same account work correctly:
- `sim_trade_cash_info(acc_id="5830137")` → equity 100,000; buying power 200,000
- `sim_trade_position_list(acc_id="5830137", market=100)` → no positions
- `sim_trade_history_order_list(...)` → no orders today

Because the challenge account is a simulator/paper account (`account_type=2`), the snapshot builder and paper-order path should use the `sim_trade_*` APIs rather than the live-account APIs. A helper script (`scripts/build_snapshot.py`) has been added to assemble snapshots from MCP JSON files.

## 2. Competition status

| Item | Value |
|---|---|
| Development/trading window | 17–28 Nov 2026 |
| Submission deadline | 30 Nov 2026, 23:59 SGT |
| Initial capital | USD 100,000 |
| Eligible products | US stocks, ETFs, options |
| Max executed orders/day | 200 (internal cap: 20) |
| Max positions | 100 (internal cap: 3) |
| Single-stock exposure | 40% |
| Source | Official event page and handbook (see skill docs) |

The competition is active. No resets/revivals are permitted.

## 3. Implementation summary

Implemented under `/data/specter-opt`:

- `src/specter_opt/pricing.py` — BSM European reference + American CRR tree with continuous-yield approximation; finite-difference Greeks; IV inversion with bracketing.
- `src/specter_opt/forecasting.py` — EWMA variance + Student-t physical scenarios; joint correlated SPY/QQQ generation.
- `src/specter_opt/surface.py` — local total-variance interpolation in log-forward-moneyness (MVP).
- `src/specter_opt/selection.py` — hard filters, scenario repricing, robust edge, CVaR, premium-aware integer sizing, score threshold.
- `src/specter_opt/risk.py` — deterministic RiskGuard with per-trade/aggregate premium limits, daily-loss block, peak-drawdown halt, persisted reservations.
- `src/specter_opt/execution.py` — persisted intents, duplicate prevention, reconciliation.
- `src/specter_opt/agent.py` — orchestrator: account verify → reconcile → forecast → screen → rank → risk gate → execute/NO_TRADE.
- `src/specter_opt/broker.py` / `moomoo_broker.py` — abstract broker + Moomoo paper adapter fed by MCP snapshots.
- `src/specter_opt/audit.py` / `dashboard.py` — JSONL decision log and HTML dashboard.
- `scripts/run_shadow.py` — standalone synthetic pipeline.
- `scripts/run_moomoo_paper.py` — snapshot-driven shadow/paper runner.
- `scripts/build_returns_cache.py` — builds SPY/QQQ log-returns cache from MCP K-line JSON.
- `scripts/build_snapshot.py` — assembles full snapshot from MCP JSON files.
- `scripts/post_to_slack.py` — posts a message to Slack via webhook.
- `scripts/daily_slack_update.py` — generates daily summary and posts to Slack.
- `scripts/generate_dashboard.py` — dashboard renderer.
- `scripts/supervise_orders.py` — lightweight deterministic order/position/fill/risk supervision.
- `src/specter_opt/agents/` — multi-agent orchestration layer:
  - `research_agent.py` — market status and account-state collection.
  - `strategy_agent.py` — SPECTER-OPT evaluation and intent generation.
  - `risk_agent.py` — risk-state monitoring and halt enforcement.
  - `execution_agent.py` — intent archival and submission preparation.
  - `reporting_agent.py` — Slack summaries and dashboard generation.
  - `orchestrator.py` — coordinates agents through a shared `AgentContext`.
- `scripts/run_agent.py` — entry point to run individual agents or the full pipeline.

Strategy scope: long single-leg calls/puts on a screener-selected universe; no shorts, borrowing, or uncovered exposure.

Dynamic universe (v1.2.0):

- `scripts/build_universe.py` aggregates `quote_option_screen` contract rows to the underlying level and ranks by a deterministic composite of log(option volume), log(open interest) and IV (weights 0.5/0.3/0.2).
- Hard filters: aggregate option volume >= 5,000, aggregate OI >= 20,000, underlying price $10–$5,000, IV 8%–200%, configurable exclusions.
- Cap 8 symbols per session; cached in `data/universe.json` with an 8-hour TTL so the 12 intraday scans do not repeat the screener call.
- `build_snapshot.py --universe` embeds the selected symbols into the snapshot; `run_moomoo_paper.py` passes them to the agent, which uses them instead of the static config list.
- Screener symbols without a configured cluster fall into `single_name` (2% premium cap), so concentration limits still bind for auto-discovered names.

Universe controls added in v1.1.0:

- Per-symbol dividend yields (SPY 1.20%, QQQ 0.55%, NVDA 0.03%, AAPL 0.40%) feed the American tree and IV inversion instead of one index-level constant.
- Single-name liquidity gates are stricter than index gates (OI >= 1000, relative spread <= 3%) because single-name wings are thinner.
- Earnings blackout drops any contract whose expiry falls on or after the next earnings date, and fails closed (skips the symbol) when no earnings calendar is supplied.
- Correlated-cluster cap: `cluster_premium_cap_pct = 2%` of equity per cluster, with multi-membership (QQQ counts against both `index` and `megacap_tech`).
- Snapshot builder, returns-cache builder and option-code parsing are now N-underlying (4-character tickers supported); legacy `--spy-*`/`--qqq-*` flags still work.

## 4. Test and validation evidence

| Test suite | Cases | Result |
|---|---|---|
| `tests/test_pricing.py` | 7 | Pass |
| `tests/test_forecasting.py` | 4 | Pass |
| `tests/test_risk.py` | 5 | Pass |
| `tests/test_selection.py` | 6 | Pass |
| `tests/test_execution.py` | 6 | Pass |
| `tests/test_universe.py` | 7 | Pass |
| `tests/test_universe_selection.py` | 6 | Pass |
| **Total** | **41/41** | **Pass** |

Validation performed:
- BSM put-call parity and IV inversion.
- American tree convergence to European call and dominance over European put.
- EWMA uses only provided return history (caller controls chronology).
- Joint scenarios preserve empirical correlation.
- Risk guard blocks daily loss, peak drawdown, and aggregate premium.
- Risk state persists across reloads.
- Execution supervisor prevents duplicate intents and survives restart.
- Single-name contracts are rejected at index-level spread/OI, and accepted at single-name thresholds.
- Earnings blackout removes contracts expiring on/after the next earnings date; missing calendars fail closed.
- Cluster headroom applies the tightest cluster for multi-membership symbols (QQQ).
- Option-code parsing resolves 4-character tickers (NVDA, AAPL, GOOGL).
- Execution supervisor reconciles partial fills.
- Agent logs broker submit-time exceptions instead of crashing.
- Agent fails closed on account mismatch and returns HOLD when no candidate passes.
- Duplicate-intent check moved before intent persistence so paper-mode submissions are not self-blocked.
- Paper mode with `--assistant-submits` persists intents to `data/pending_paper_orders.jsonl` for assistant submission via MCP.
- Multi-agent orchestrator runs the full pipeline (research → strategy → risk → execution → reporting) end-to-end.

## 5. Shadow-mode demonstration

### Synthetic run
`scripts/run_shadow.py` completes end-to-end and emits an explicit `HOLD`/`NO_TRADE` when conservative score threshold is not met.

### Real-data snapshot run
A snapshot was built from live MCP quotes (SPY/QQQ options expiring 2026-11-24, data timestamp 2026-11-17). Running `scripts/run_moomoo_paper.py --snapshot data/snapshot_20261117.json --mode shadow` produced:

```
Account: Moomoo x Qoder AI Paper Trading Agent Challenge
Equity: 100,000.00
Action: HOLD
Reason: no_candidate
Halted: false
```

### Real-data snapshot run with historical returns cache
A returns cache was built from one year of MCP daily K-lines for SPY/QQQ (`scripts/build_returns_cache.py`, 250 trading days) and injected into the snapshot (`data/snapshot_20261117_realized.json`). Re-running in shadow mode produced the same conservative result:

```
Account: Moomoo x Qoder AI Paper Trading Agent Challenge
Equity: 100,000.00
Action: HOLD
Reason: no_candidate
Halted: false
```

This confirms stable abstention under the zero-drift M0 baseline even when the EWMA forecast is fed real historical returns: option ask prices and costs do not support a positive conservative net expected value.

### Fresh full-market snapshot run
A complete live snapshot was assembled on 2026-11-17 from:
- `sim_trade_cash_info` / `sim_trade_position_list` / `sim_trade_history_order_list` for account `5830137`
- Fresh SPY/QQQ option chains for expiries 24 Nov – 4 Dec 2026 (7–17 DTE)
- `quote_market_snapshot` for 732 near-the-money contracts to obtain live bid/ask, Greeks, and open interest
- The historical returns cache

`scripts/build_snapshot.py` produced `data/snapshot_fresh.json` (384 SPY + 348 QQQ contracts). Running `scripts/run_moomoo_paper.py --snapshot data/snapshot_fresh.json --mode shadow` produced:

```
Account: Moomoo x Qoder AI Paper Trading Agent Challenge
Equity: 100,000.00
Action: HOLD
Reason: no_candidate
Halted: false
```

Even with live bid/ask/Greeks and real returns, the conservative filters and zero-drift M0 baseline produce no trade. This is the expected fail-closed behavior.

### Paper-mode authorization run
On 2026-11-17 the user explicitly authorized autonomous paper trading until 1 Dec 2026. Running `scripts/run_moomoo_paper.py --snapshot data/snapshot_fresh.json --mode paper --assistant-submits --out data/run_result_paper.json` produced:

```
Account: Moomoo x Qoder AI Paper Trading Agent Challenge
Equity: 100,000.00
Action: HOLD
Reason: no_candidate
Halted: false
```

No pending intents were written to `data/pending_paper_orders.jsonl`, so no `sim_trade_input_order` calls were required. The agent is now live in paper mode under the daily Forward schedule.

## 6. Risk controls

| Control | Setting | Evidence |
|---|---|---|
| Per-trade premium + entry cost | 0.5% equity | Enforced in `RiskGuard.can_enter` |
| Aggregate open premium | 3% equity | Enforced incl. existing, pending, reserved |
| Concurrent positions | 3 | Enforced by position count |
| Daily equity loss block | 2% | Tested and persisted |
| Peak drawdown halt | 5% | Tested and persisted |
| Max orders/day | 20 | Counter persisted |
| Short options / borrowing / uncovered | Disabled | Strategy filters + risk flags |
| Expiry buffer | ≥1 session before expiry | DTE filter 7–21 days |
| Limit orders only | Yes | `order_type="LIMIT"` |

## 7. Automation and schedules

Current mode: **paper**, authorized by the user until 1 Dec 2026. Six Forward schedules are active:

| Schedule | Cadence | Purpose |
|---|---|---|
| `SPECTER-OPT Research Briefing` | 09:00 ET weekdays | Events, market conditions, account state |
| `SPECTER-OPT First Entry Evaluation` | 10:00 ET weekdays | Initial candidate scan after open |
| `SPECTER-OPT Strategy Scan` | Every 30 min, 10:00–15:00 ET weekdays | Refresh forecasts and compare contracts |
| `SPECTER-OPT Order/Position Supervision` | Every 5 min, 09:00–16:00 ET weekdays | Reconcile fills, enforce risk, manage exits |
| `SPECTER-OPT EOD Review` | 15:30 ET weekdays | Overnight exposure and expiry obligations |
| `SPECTER-OPT Performance Report` | 16:15 ET weekdays | Reconcile results, costs, failures |
| `SPECTER-OPT Paper Auto-Pause` | 1 Dec 2026 14:30 UTC | Stop submissions and notify user |
| `SPECTER-OPT Credit Monitor` | Every hour | Post Slack alert if credits < 100 |

Each strategy scan (research/entry/30-min) runs:
1. Query account/positions/orders via `sim_trade_*` MCP APIs.
2. Fetch fresh SPY/QQQ option chains and `quote_market_snapshot`.
3. Run `scripts/build_snapshot.py` to assemble `data/snapshot_fresh.json`.
4. Run `scripts/run_moomoo_paper.py --snapshot data/snapshot_fresh.json --mode paper --assistant-submits --out data/run_result_paper.json`.
5. For any pending intent, fetch a fresh `quote_market_snapshot` for that symbol before submitting to verify the limit price is still executable. Skip stale/widened-spread quotes.
6. Submit valid intents via `sim_trade_input_order(acc_id='5830137', market=100, ...)`, archive them to `data/pending_paper_orders_history.jsonl`, and clear `data/pending_paper_orders.jsonl`.
7. Reconcile fills and update persisted state.
8. Post a Slack summary only on material events (new order, fill, halt, top candidate above threshold).
9. Update `data/dashboard.html`.

The supervision schedule runs `scripts/supervise_orders.py` every 5 minutes. The script compares current MCP state to the previous snapshot, updates `data/intents.jsonl` and `data/risk_state.json`, and posts to Slack only on material events (new fills, rejects, expiring positions, risk halts).

Credit monitoring:
- `scripts/check_credits.py` reads `CREDITS_REMAINING` from `data/.credits.env`.
- `SPECTER-OPT Credit Monitor` runs every hour. If credits drop below 100, it posts a Slack warning.
- The assistant cannot query the platform credit API directly; the user must keep `data/.credits.env` updated.

Slack integration:
- Webhook stored in `data/.slack_webhook.env` (mode 600).
- `scripts/post_to_slack.py` posts a plain-text payload.
- `scripts/daily_slack_update.py` generates summaries and posts them.
- `scripts/supervise_orders.py` posts supervision alerts.
- Test posts sent successfully (HTTP 200, body `ok`).

Slack integration:
- Webhook stored in `data/.slack_webhook.env` (mode 600).
- `scripts/post_to_slack.py` posts a plain-text payload.
- `scripts/daily_slack_update.py` generates the summary and posts it.
- A test post was sent successfully (HTTP 200, body `ok`).

**Paper-order activation is now live under explicit user authorization until 2026-12-01.**

## 8. Pause, shutdown, recovery and emergency

- **Pause new risk**: set `SPECTER_MODE=halt` or call `RiskGuard.manual_halt(reason)`.
- **Resume**: verify state and call `RiskGuard.manual_resume()`.
- **Shutdown**: cancel open orders via Moomoo platform; preserve decision logs.
- **Recovery**: restart reads persisted `data/risk_state.json` and `data/intents.jsonl`; reconcile with broker before any new entries.
- **Emergency**: if risk state is corrupt, delete `data/risk_state.json` and re-establish day-start equity manually.

## 9. Known limitations and unresolved items

1. **M0 baseline only.** Ridge/regime/skew challengers (M1–M3) are not implemented; no validated directional alpha exists yet.
2. **Student-t dollar-tail caveat.** Unbounded Student-t log returns have no finite positive exponential moment; simulated dollar EV may be unstable. The current implementation uses finite samples and a zero-drift baseline; tail behavior should be monitored.
3. **No historical option data.** Forward paper results cannot be compared to backtested option returns; only underlying forecast tests and synthetic pricing tests are available.
4. **Returns cache now connected.** A historical cache (250 days) has been built, but it is point-in-time close data; intraday or option-specific returns are still unavailable.
5. **Fee rounding semantics.** Competition fee schedule is implemented per contract/side; exact per-order rounding should be validated against simulator fills.
6. **Snapshot build is assistant-driven.** A fully automated MCP→snapshot builder is not yet implemented; the assistant currently assembles snapshots and calls MCP tools.
7. **New multi-schedule automation live.** Seven Forward schedules cover research, entry evaluation, 30-minute scans, 15-minute supervision, EOD review, performance report, hourly credit monitor, and auto-pause. Every trading-oriented schedule now starts with a `quote_market_state` check and exits silently when the market is closed, on holiday, or outside regular hours. Schedules run from `/data/specter-opt` using the multi-agent pipeline.
8. **Live-account MCP scope missing, but sim-trade APIs work.** `account_positions`, `account_orders_active`, and `account_funds` return `Unauthorized` for `5830137`, but the equivalent `sim_trade_*` APIs succeed. The snapshot builder and order path therefore use `sim_trade_*` calls. `scripts/build_snapshot.py` now assembles a full snapshot from MCP JSON files, but the assistant still has to call MCP tools and feed the JSON files into it.

## 10. Recommendation

The agent is **authorized for autonomous paper trading until 1 Dec 2026**. The first paper-mode run produced `HOLD`/`no_candidate`, confirming stable fail-closed behavior. All implemented tests pass, the historical returns cache is connected, and risk guards are active. The daily Forward schedule will now assemble a fresh snapshot, run the agent in paper mode, submit any pending intents via `sim_trade_input_order`, reconcile fills, and post a Slack summary.

Automated paper order submission will remain active until the `SPECTER-OPT Paper Auto-Pause` schedule fires on 1 Dec 2026 14:30 UTC, or until the user revokes authorization earlier.

Current operating mode: **paper**.
Authorization expiry: **2026-12-01 14:30 UTC**.
Execution owner: this session / specter.

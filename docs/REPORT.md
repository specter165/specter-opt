# SPECTER-OPT — Agent Report

**Moomoo x Qoder AI Paper Trading Agent Challenge**
Paper account `5830137` · $100,000 · authorized through 2026-12-01
Repo: `https://github.com/specter165/specter-opt`

---

## 1. What this agent is

An autonomous, risk-controlled options agent that runs on a schedule, prices the
option market against its own distribution, and mostly decides not to trade.

It is not a signal generator pointed at a fixed ticker list. The tradable universe is
re-derived from the market each morning, the entry test is a comparison of two
distributions rather than a technical indicator, and every limit is enforced in code
with persisted state so a restart cannot forget it.

---

## 2. Architecture

```
                    ┌───────────────────────────────┐
  Qoder Forward     │  9 cron schedules             │
  scheduler ───────▶│  scan · supervise · report    │
                    └──────────────┬────────────────┘
                                   │ fresh sandbox → git clone
                                   ▼
   ┌────────────────────────────────────────────────────────────┐
   │  Moomoo MCP tools                                          │
   │  quote_option_screen · quote_option_chain ·                │
   │  quote_market_snapshot · quote_stock_quote ·               │
   │  sim_trade_cash_info / position_list / input_order         │
   └───────────────┬────────────────────────────────────────────┘
                   │ JSON payloads (saved to data/)
                   ▼
   ┌───────────────┴────────────────────────────────────────────┐
   │  build_universe.py   screener → top-8 underlyings          │
   │  build_snapshot.py   MCP JSON → normalised snapshot        │
   └───────────────┬────────────────────────────────────────────┘
                   ▼
   ┌────────────────────────────────────────────────────────────┐
   │  SpecterAgent.run()                                        │
   │    verify account ▸ trading day ▸ quotes ▸ chains          │
   │    ▸ IV imputation ▸ scenarios ▸ screen ▸ rank ▸ size      │
   │    ▸ risk gate ▸ intent                                    │
   └───────────────┬────────────────────────────────────────────┘
                   ▼
        HOLD  (no candidate)  ──or──  limit intent → paper order
```

### Modules

| Module | Responsibility |
|---|---|
| `config.py` | Every limit as a frozen dataclass; no magic numbers in logic |
| `universe.py` | Screener aggregation, filters, deterministic ranking, 8h cache |
| `pricing.py` | CRR American binomial tree; BSM European reference; IV inversion |
| `forecasting.py` | EWMA variance + Student-t scenarios (M0 zero-drift baseline) |
| `selection.py` | Hard filters, robust edge, CVaR95, integer sizing |
| `risk.py` | Premium budgets, cluster caps, drawdown halts, reservations |
| `agent.py` | Orchestration, earnings gate, IV imputation, decision logging |
| `moomoo_broker.py` | Snapshot-backed broker adapter; order intent plumbing |
| `scripts/` | Runners, universe builder, snapshot builder, dashboard, bootstrap |

---

## 3. The decision loop

Executed every 30 minutes during US hours.

1. **Bootstrap.** Clone the repo fresh; verify the expected CLI surface exists. A stale
   copy aborts the run rather than silently executing old code.
2. **Universe.** Aggregate `quote_option_screen` by underlying; apply hard liquidity
   filters; rank by a z-scored composite; keep 8; cache for 8 hours.
3. **Data.** Chains, underlying quotes, option snapshots (bid/ask/OI/IV/greeks),
   account, positions, orders.
4. **Normalise.** Percent IV → decimal. Missing underlying IV → imputed from
   near-the-money chain contracts and logged.
5. **Gate.** Earnings blackout (fail closed), quote freshness, delta/DTE/spread/OI.
6. **Price.** CRR American tree per contract, with per-symbol dividend yield.
7. **Score.** Scenario EV minus a CVaR95 penalty → `robust_edge`.
8. **Size.** Integer contracts against per-trade, aggregate and cluster budgets.
9. **Decide.** Order, or `HOLD / no_candidate` with the reason written to the log.

---

## 4. What it actually did

### First live run on the new methodology (2026-11-17)

| Stage | Result |
|---|---|
| Screener candidates | 23 underlyings → 114 excluded on hard filters |
| Universe | SPY, NVDA, QQQ, IWM, IBIT, INTC, MSTR, SPCX |
| Contracts in band (7–21 DTE, \|Δ\| 0.35–0.70) | 644 |
| Screened candidates evaluated | 147 (SPY 51, QQQ 54, IWM 42) |
| With positive robust edge | **0** |
| Best candidate | IWM 261127 272P, Δ −0.56, EV **−$87.71** |
| Decision | **HOLD** — no intents, no orders |
| Blocked by earnings gate | NVDA, IBIT, INTC, MSTR, SPCX (`missing_earnings_calendar`) — since relaxed |

This run used **real 60-day EWMA volatilities** built from daily K-lines
(`scripts/build_returns_cache.py` → `data/runs/returns_cache.json`). An earlier run
without a returns cache defaulted volatility to zero, which priced every long option at
intrinsic and produced a spurious EV of ≈ −premium for everything; that run's HOLD was
an input artefact, not a market verdict, and is superseded by this one.

With proper inputs the result is now a genuine judgement:

| Underlying | EWMA realised vol (ann.) | Implied vol | IV − RV |
|---|---|---|---|
| SPY | 20.8% | 26.0% | +5.3 |
| QQQ | 32.3% | 35.2% | +2.8 |
| IWM | 23.5% | 28.0% | +4.5 |
| INTC | 119.1% | 83.0% | **−36.1** |

On every tradeable index name the market's implied vol sits above realised, so a
long-premium book is paying up for movement it is not being handed — the variance risk
premium working against a buyer. INTC is the one name where realised exceeds implied
(RV − IV = −36 vol points), i.e. the only place today the thesis would fire, but at the
time it was blocked by the fail-closed earnings gate because no forward earnings date is
available for it.

**Since relaxed.** Moomoo exposes no forward earnings dates at all
(`quote_economic_calendar_search` returns only released events), so failing closed meant
no single name could ever be traded. `require_earnings_calendar` now defaults to `False`:
an unknown release date no longer blocks the name, but contracts on such names are capped
at `unknown_earnings_max_dte = 10` days so an unannounced release cannot sit deep inside
the holding period. Known dates still black out normally, and
`require_earnings_calendar=True` restores the old behaviour if needed. Each relaxed
underlying is logged as `EARNINGS_UNKNOWN / calendar_unavailable_dte_capped`.

### Operational history

- 14 scheduled supervision runs reported "prerequisites absent" — a genuine
  deployment failure, not a market verdict. Root cause: schedule sandboxes start empty
  and the prompts searched for a repo rather than cloning one.
- Fixed by hardcoding the clone, adding a stale-repo check, and making bootstrap create
  the runtime directories. Supervision then correctly detected a fill, re-baselined
  two stale orders, and posted to Slack (HTTP 200).

---

## 5. Risk controls

See `docs/THESIS.md` §4 for the full table. Summary:

- 1.0% equity premium per trade · 3% aggregate · 2% per correlation cluster · 3 positions
- 30% premium stop · close one session before expiry
- 2% daily loss → no new entries · 5% peak drawdown → persisted halt
- 20 orders/day · long single-leg only · no shorts, no borrowing, no uncovered
- Earnings blackout, fail closed · stale quotes rejected · reconciliation before submit
- Fail-closed default: an exception produces no order, never a best guess

---

## 6. What we would build next

1. **Earnings calendar ingestion.** The gate now allows a name with no known date but
   caps its contract life at 10 DTE, which is a holding-period proxy for event risk. The
   real fix is a validated dates cache — last report date from the broker plus a widened
   ±7-day blackout window — so the cap can lift without ever failing open.
2. **Short premium, cash-secured puts only.** The variance risk premium sits on the
   selling side; long premium is the hard half of the trade. Requires a collateral-based
   risk budget instead of a premium-based one.
3. **Take-profit / trailing exit.** Today's only exit is a 30% stop. A winner that
   round-trips gives back the gain without ever tripping it.
4. **Volatility targeting.** Size is premium-budgeted, not risk-scaled, so per-trade
   risk varies with the regime.

---

## 7. Honest assessment

The engineering is the strong part: deterministic sizing, persisted risk state,
fail-closed defaults, a test suite covering the failure modes that actually occurred,
and a deployment that now recovers itself.

The trading record is not yet a record. Two weeks and a handful of runs — most of them
spent fixing deployment — cannot establish an edge, and forcing trades to manufacture
one would destroy the only defensible claim this system has: that it declines to trade
when it cannot price an advantage.

A flat week here is the strategy working as specified.

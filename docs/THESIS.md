# SPECTER-OPT — Trading Thesis, Edge, and Invalidation

Paper account `5830137` · $100,000 · authorized through 2026-12-01.
This document states what the agent believes, why it should make money, what would
prove it wrong, and what stops it from losing more than it should.

---

## 1. Thesis

**Options markets price short-horizon dispersion from implied volatility, and implied
volatility is set by dealer hedging flow rather than by the realised dispersion that
follows.** In liquid, high-activity underlyings, realised moves have fatter tails than
the implied distribution admits. A long option is a claim on that tail: the loss is
bounded at the premium, the gain is not.

Therefore: **buy convexity, but only when the gap between scenario-implied value and
market price survives a fat-tail penalty.** Not "buy options because they can pay" —
buy only the specific contracts where the model's physical-measure distribution prices
them above the ask after fees, and where the uncertainty in that estimate is small
enough that the gap is still positive.

The edge is *not* directional forecasting. It is a pricing disagreement, and it is
deliberately allowed to be wrong most of the time, because the payoff is asymmetric.

### Why this edge could exist

1. **Variance risk premium.** Implied vol systematically exceeds subsequent realised
   vol on average. Long premium is normally the wrong side of that trade — which is
   exactly why a *selective* long-premium book can work where a blanket one cannot.
2. **Dealer gamma hedging** amplifies realised moves around large open-interest
   strikes, widening the realised tail beyond what a smooth implied surface implies.
3. **Event clustering.** Catalysts concentrate realised dispersion; the surface
   reprices unevenly, especially in the week or two after one event and before the next.

### Why it usually does not work

- Theta. Every day held is a day paid.
- The M0 forecast baseline is **zero-drift**. With no directional view, the model has
  no reason to prefer a long option unless pure dispersion compensates the premium.
  `no_candidate` is the intended steady state, not a malfunction.
- Fees and spread. A 3–5 cent wide book on a $3 premium is already 1–2% of edge.

**Consequence: this is a low-frequency strategy. Expected trade count over a two-week
window is small. Flat is a valid, intended output.**

---

## 2. What the agent actually does

1. **Universe (daily, 09:00–10:00 ET).** Moomoo `quote_option_screen` → aggregate by
   underlying → hard filters (option volume ≥ 5,000; OI ≥ 20,000; underlying $10–$5,000;
   IV 8%–200%) → rank by composite z-score (0.5·log volume + 0.3·log OI + 0.2·IV) →
   top 8, cached 8 hours.
2. **Contract filters.** 7–21 DTE; |delta| 0.35–0.70; single names need OI ≥ 1,000 and
   relative spread ≤ 3% (index: OI ≥ 500, spread ≤ 5%); quote age ≤ 10s.
3. **Earnings blackout.** No contract whose life spans the next earnings date. If the
   calendar is missing, no single-name trading at all — fail closed.
4. **Edge test.** EWMA variance (λ=0.94) + Student-t (ν=5) scenarios, 5,000 paths,
   fixed seed. Price with a CRR American tree, 5 steps/day, continuous dividend yield.
   `robust_edge = E[net P&L] − 1.0 × (CVaR95 shortfall dispersion)`. Trade only if
   `robust_edge > 0` **and** composite score > 0.
5. **Sizing.** Integer contracts priced against the premium budget, never rounded up.
6. **Execution.** Limit only. Persisted intents, duplicate prevention, reconciliation
   against broker state before and after submission.

---

## 3. Conditions that invalidate the strategy

Written in advance, so the result cannot be reinterpreted after the fact. Any one of
these, observed over a live sample, is grounds to stop and revise — not to tune.

| # | Invalidation | Measurement | Threshold |
|---|---|---|---|
| I1 | **Edge is imaginary** | Realised net P&L on executed trades | ≤ 0 over ≥ 30 trades |
| I2 | **No convexity** | Realised net P&L distribution | largest single winner < 3× its entry premium over ≥ 30 trades — the fat-tail payoff the thesis requires never arrives (profit concentration itself is *expected*, not a failure) |
| I3 | **Variance premium is against us** | Implied minus subsequently realised vol in the selected universe | **positive** on average over ≥ 20 sessions — we are systematically paying more than is realised, the adverse state for a long-premium book |
| I4 | **Selection adds nothing** | Realised P&L of *rejected* candidates vs accepted | rejected outperform accepted |
| I5 | **Single-event concentration** | Share of aggregate open premium in contracts expiring inside the same event window | > 60% — the book is one binary catalyst bet, not dispersion (event clustering is an edge *source*, but concentration is a risk) |
| I6 | **Fills destroy the edge** | Slippage vs decision mid | > 1.5% of premium on > 30% of fills |
| I7 | **Model mis-specification** | IV unit/scale sanity; implied vol vs tree-implied vol round-trip | round-trip error > 50 bps without explanation |

**Decision rule:** if I1 or I4 triggers, the strategy is halted and the model is
re-specified before any further orders. It is never rescued by loosening thresholds.

---

## 4. Risk controls

All limits are enforced in `src/specter_opt/risk.py` and persisted in
`data/risk_state.json`, so a crashed or restarted run cannot forget them.

### Position limits

| Control | Value | Notes |
|---|---|---|
| Premium per trade | 1.0% equity ($1,000) | includes entry cost and fees; one SPY contract must fit |
| Aggregate open premium | 3.0% equity ($3,000) | exactly three full-size positions (3 × 1.0%) |
| Correlated cluster | 2% equity ($2,000) | `index` = {SPY, QQQ}; `megacap_tech` = {QQQ, NVDA, AAPL}; screener names → `single_name` |
| Concurrent positions | 3 | |
| Orders per US trading day | 20 | |
| Structure | long single-leg only | no spreads, no naked, no borrowing, no uncovered |
| Earnings | no contract spanning earnings | fail closed without calendar |
| Quote freshness | ≤ 10 seconds | stale data → no entry |

Cluster membership is multi-valued: a QQQ position consumes both the `index` and
`megacap_tech` budgets, so correlated exposure cannot quietly stack.

### Drawdown response

| Trigger | Response |
|---|---|
| −30% on a position's premium | close the position |
| ≤ 1 session to expiry | close before expiry, never hold to settlement |
| −2% equity in one day | no new entries for the rest of the session |
| −5% from peak equity | **halt**: no new entries until manually reset |

### Kill switches

1. **Peak drawdown halt (5%)** — persisted; survives restart; requires explicit reset.
2. **Daily loss block (2%)** — automatic, scoped to the session.
3. **Missing earnings calendar** — contract life capped at 10 DTE rather than the name
   disabled; a known date inside the life still blocks the contract.
4. **Stale or missing quotes** — no order is constructed from data older than 10s.
5. **Broker/state disagreement** — reconciliation failure aborts the run before submit.
6. **Order budget (20/day)** — hard stop on runaway loops.
7. **Campaign expiry (2026-12-01)** — scheduled auto-pause archives every schedule and
   cancels working orders.
8. **Fail-closed default** — any unhandled exception results in no order, never in a
   best-guess order.

---

## 5. Known limitations, stated plainly

- **No short premium.** Cash-secured puts are the natural next step and would widen the
  edge materially (the variance risk premium is on the selling side), but the paper API
  exposed here is single-leg and the risk model is denominated in premium, not
  collateral. Deliberately deferred rather than half-built.
- **The book may contain a manually placed contract** not chosen by this strategy. Such
  positions are excluded from strategy evidence and should be attributed explicitly.
- **No volatility targeting.** Position size is premium-budgeted, not vol-scaled, so
  risk per trade varies with the VIX regime.
- **No loss-streak ladder.** Three consecutive losers do not shrink size; only the
  drawdown halts bite.
- **Two-week sample.** Any conclusion drawn from ≤ 30 trades is statistically thin and
  will be reported as such.

---

## 6. Summary

- **Thesis:** implied dispersion is systematically under-priced in liquid names because
  IV is set by flow, not by realised tails.
- **Edge:** buy single-leg convexity only where scenario EV, after a CVaR95 fat-tail
  penalty and fees, remains positive.
- **Invalidation:** seven pre-committed falsification tests; I1 or I4 halts the strategy.
- **Risk:** 1.0% per trade / 3% aggregate / 2% per cluster / 3 positions / 30% stop /
  2% daily block / 5% peak halt / hard expiry.
- **Expected behaviour:** mostly `HOLD`. A flat week is the strategy working, not failing.

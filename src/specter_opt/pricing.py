"""Option pricing: BSM European reference and American CRR tree.

Dividend handling uses a continuous yield approximation for ETF options.
American exercise is implemented with a Cox-Ross-Rubinstein tree.
"""

from dataclasses import dataclass
from typing import Literal, Tuple

import numpy as np
from scipy.stats import norm


@dataclass(frozen=True)
class PricingResult:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    intrinsic: float
    status: str


def bsm_price(
    S: float,
    K: float,
    tau: float,
    r: float,
    q: float,
    sigma: float,
    right: Literal["CALL", "PUT"],
) -> float:
    """Black-Scholes-Merton European option price with continuous yield."""
    if tau <= 0:
        if right == "CALL":
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        # Degenerate case: intrinsic present value
        if right == "CALL":
            return max(S * np.exp(-q * tau) - K * np.exp(-r * tau), 0.0)
        return max(K * np.exp(-r * tau) - S * np.exp(-q * tau), 0.0)
    sqrt_tau = np.sqrt(tau)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * tau) / (sigma * sqrt_tau)
    d2 = d1 - sigma * sqrt_tau
    if right == "CALL":
        return S * np.exp(-q * tau) * norm.cdf(d1) - K * np.exp(-r * tau) * norm.cdf(d2)
    return K * np.exp(-r * tau) * norm.cdf(-d2) - S * np.exp(-q * tau) * norm.cdf(-d1)


def bsm_greeks(
    S: float,
    K: float,
    tau: float,
    r: float,
    q: float,
    sigma: float,
    right: Literal["CALL", "PUT"],
) -> dict:
    """European Greeks via closed-form BSM (analytical reference)."""
    if tau <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    sqrt_tau = np.sqrt(tau)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * tau) / (sigma * sqrt_tau)
    d2 = d1 - sigma * sqrt_tau
    nd1 = norm.pdf(d1)
    if right == "CALL":
        delta = np.exp(-q * tau) * norm.cdf(d1)
    else:
        delta = -np.exp(-q * tau) * norm.cdf(-d1)
    gamma = np.exp(-q * tau) * nd1 / (S * sigma * sqrt_tau)
    vega = S * np.exp(-q * tau) * nd1 * sqrt_tau  # per unit vol
    theta_common = (
        -S * np.exp(-q * tau) * nd1 * sigma / (2 * sqrt_tau)
        + q * S * np.exp(-q * tau) * (norm.cdf(d1) if right == "CALL" else -norm.cdf(-d1))
        - r * K * np.exp(-r * tau) * (norm.cdf(d2) if right == "CALL" else -norm.cdf(-d2))
    )
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta_common}


def american_tree(
    S: float,
    K: float,
    tau: float,
    r: float,
    q: float,
    sigma: float,
    right: Literal["CALL", "PUT"],
    n_steps: int = 30,
) -> PricingResult:
    """American option price via CRR binomial tree with continuous dividend yield.

    Returns price and finite-difference Greeks.
    """
    if tau <= 0:
        intrinsic = max(S - K, 0.0) if right == "CALL" else max(K - S, 0.0)
        return PricingResult(intrinsic, 0.0, 0.0, 0.0, 0.0, intrinsic, "expired")
    if sigma <= 0:
        if right == "CALL":
            price = max(S * np.exp(-q * tau) - K * np.exp(-r * tau), 0.0)
        else:
            price = max(K * np.exp(-r * tau) - S * np.exp(-q * tau), 0.0)
        intrinsic = max(S - K, 0.0) if right == "CALL" else max(K - S, 0.0)
        return PricingResult(price, 0.0, 0.0, 0.0, 0.0, intrinsic, "degenerate")

    n_steps = max(3, n_steps)
    dt = tau / n_steps
    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)

    if not (0 <= p <= 1):
        # Invalid discretization for given inputs (e.g., very high q)
        price = bsm_price(S, K, tau, r, q, sigma, right)
        intrinsic = max(S - K, 0.0) if right == "CALL" else max(K - S, 0.0)
        return PricingResult(price, 0.0, 0.0, 0.0, 0.0, intrinsic, "invalid_tree_discretization")

    # Terminal payoffs
    prices = S * (u ** np.arange(n_steps, -1, -1)) * (d ** np.arange(0, n_steps + 1))
    if right == "CALL":
        values = np.maximum(prices - K, 0.0)
        intrinsic_all = np.maximum(prices - K, 0.0)
    else:
        values = np.maximum(K - prices, 0.0)
        intrinsic_all = np.maximum(K - prices, 0.0)

    df = np.exp(-r * dt)
    for step in range(n_steps - 1, -1, -1):
        values = df * (p * values[:-1] + (1 - p) * values[1:])
        prices = prices[:-1] / u  # move back one step
        values = np.maximum(values, intrinsic_all[: len(values)])

    price = values[0]

    # Finite-difference Greeks using small bumps
    bump = 0.01 * S
    price_up = american_tree_raw(S + bump, K, tau, r, q, sigma, right, n_steps)
    price_down = american_tree_raw(S - bump, K, tau, r, q, sigma, right, n_steps)
    delta = (price_up - price_down) / (2 * bump)
    gamma = (price_up - 2 * price + price_down) / (bump ** 2)

    vol_bump = 0.001
    price_vol_up = american_tree_raw(S, K, tau, r, q, sigma + vol_bump, right, n_steps)
    price_vol_down = american_tree_raw(S, K, tau, r, q, sigma - vol_bump, right, n_steps)
    vega = (price_vol_up - price_vol_down) / (2 * vol_bump)

    time_bump = max(1 / 252, tau * 0.01)
    if tau - time_bump > 0:
        price_t_down = american_tree_raw(S, K, tau - time_bump, r, q, sigma, right, n_steps)
        theta = (price_t_down - price) / time_bump
    else:
        theta = 0.0

    return PricingResult(price, delta, gamma, vega, theta, intrinsic_all[0], "ok")


def american_tree_raw(
    S: float,
    K: float,
    tau: float,
    r: float,
    q: float,
    sigma: float,
    right: Literal["CALL", "PUT"],
    n_steps: int = 30,
) -> float:
    """Raw American tree price without Greeks (helper)."""
    if tau <= 0:
        return max(S - K, 0.0) if right == "CALL" else max(K - S, 0.0)
    if sigma <= 0:
        if right == "CALL":
            return max(S * np.exp(-q * tau) - K * np.exp(-r * tau), 0.0)
        return max(K * np.exp(-r * tau) - S * np.exp(-q * tau), 0.0)

    dt = tau / n_steps
    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)
    if not (0 <= p <= 1):
        return bsm_price(S, K, tau, r, q, sigma, right)

    prices = S * (u ** np.arange(n_steps, -1, -1)) * (d ** np.arange(0, n_steps + 1))
    if right == "CALL":
        values = np.maximum(prices - K, 0.0)
    else:
        values = np.maximum(K - prices, 0.0)

    df = np.exp(-r * dt)
    for step in range(n_steps - 1, -1, -1):
        values = df * (p * values[:-1] + (1 - p) * values[1:])
        prices = prices[:-1] / u
        if right == "CALL":
            values = np.maximum(values, prices - K)
        else:
            values = np.maximum(values, K - prices)
    return values[0]


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    tau: float,
    r: float,
    q: float,
    right: Literal["CALL", "PUT"],
    american: bool = True,
    n_steps: int = 30,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> Tuple[float, str]:
    """Solve for implied volatility given market price using American tree or BSM."""
    if market_price <= 0 or tau <= 0:
        return 0.0, "invalid_input"

    def target(sigma):
        if american:
            return american_tree_raw(S, K, tau, r, q, sigma, right, n_steps) - market_price
        return bsm_price(S, K, tau, r, q, sigma, right) - market_price

    # Bracket
    low, high = 0.001, 5.0
    f_low, f_high = target(low), target(high)
    if f_low * f_high > 0:
        return 0.0, "no_bracket"

    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        f_mid = target(mid)
        if abs(f_mid) < tol:
            return mid, "ok"
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return 0.5 * (low + high), "max_iter"

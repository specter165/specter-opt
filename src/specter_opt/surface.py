"""Volatility surface interpolation in log-forward-moneyness / total variance space.

MVP uses local linear interpolation. SVI is deferred.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class VolPoint:
    strike: float
    expiry_days: int
    iv: float
    right: str


def log_moneyness(S: float, K: float, r: float, tau: float) -> float:
    F = S * np.exp(r * tau)
    return np.log(K / F)


def total_variance(iv: float, tau: float) -> float:
    return (iv ** 2) * tau


def local_total_variance_interpolator(
    points: List[VolPoint],
    S: float,
    r: float,
    tau: float,
) -> Tuple[Optional[float], str]:
    """Linear interpolation of total variance in log-forward-moneyness.

    Returns implied volatility or None if outside trusted domain.
    """
    if not points or tau <= 0:
        return None, "no_data"
    k0 = log_moneyness(S, S, r, tau)
    ks = []
    ws = []
    for p in points:
        k = log_moneyness(S, p.strike, r, tau)
        w = total_variance(p.iv, tau)
        ks.append(k)
        ws.append(w)
    ks = np.array(ks)
    ws = np.array(ws)
    order = np.argsort(ks)
    ks = ks[order]
    ws = ws[order]

    if k0 < ks[0] or k0 > ks[-1]:
        return None, "extrapolation"

    w_interp = np.interp(k0, ks, ws)
    iv = np.sqrt(max(w_interp, 0.0) / tau)
    return iv, "ok"


def get_atm_iv(
    chain_points: List[VolPoint],
    S: float,
    r: float,
    tau: float,
) -> Tuple[Optional[float], str]:
    iv, status = local_total_variance_interpolator(chain_points, S, r, tau)
    if iv is None:
        # Fallback: nearest strike IV
        if not chain_points:
            return None, "no_data"
        atm = min(chain_points, key=lambda p: abs(p.strike - S))
        return atm.iv, "nearest_fallback"
    return iv, status

"""Physical-measure scenario generation: EWMA volatility + Student-t shocks.

M0: zero-drift baseline.
M1/M2/M3: placeholders for ridge/regime/skew challengers.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class ScenarioSet:
    underlying: str
    horizon: int
    as_of: str
    model: str
    spots: np.ndarray
    ivs: np.ndarray
    params: dict
    seed: int


class EWMAStudentTForecast:
    """EWMA variance with Student-t innovations."""

    def __init__(
        self,
        lambda_: float = 0.94,
        nu: float = 5.0,
        seed: Optional[int] = 42,
        paths: int = 5000,
    ):
        self.lambda_ = lambda_
        self.nu = max(2.1, nu)
        self.seed = seed
        self.paths = paths

    def estimate_variance(self, log_returns: np.ndarray) -> float:
        """Point-in-time EWMA variance using last observation."""
        if len(log_returns) == 0:
            return 0.0001
        var = log_returns[0] ** 2
        for r in log_returns[1:]:
            var = self.lambda_ * var + (1 - self.lambda_) * r ** 2
        return max(var, 1e-12)

    def generate(
        self,
        underlying: str,
        current_price: float,
        current_iv: float,
        log_returns: np.ndarray,
        horizon: int,
        model: str = "M0",
        conditional_mean: Optional[np.ndarray] = None,
        iv_shocks: Optional[np.ndarray] = None,
    ) -> ScenarioSet:
        rng = np.random.default_rng(self.seed)
        var = self.estimate_variance(log_returns)
        std = np.sqrt(var)

        # Student-t shock scaled to unit variance
        t = rng.standard_t(self.nu, size=(self.paths, horizon))
        scale = np.sqrt((self.nu - 2) / self.nu)
        shocks = t * scale

        if conditional_mean is None:
            conditional_mean = np.zeros(horizon)

        daily_returns = conditional_mean + std * shocks
        cumulative = daily_returns.sum(axis=1)
        spots = current_price * np.exp(cumulative)

        if iv_shocks is None:
            # Base: sticky strike / mild random IV changes correlated with return sign
            iv_shocks = rng.normal(0, 0.02, size=self.paths)
        ivs = np.clip(current_iv + iv_shocks, 0.05, 2.0)

        return ScenarioSet(
            underlying=underlying,
            horizon=horizon,
            as_of="now",
            model=model,
            spots=spots,
            ivs=ivs,
            params={
                "lambda": self.lambda_,
                "nu": self.nu,
                "ewma_var": float(var),
                "ewma_vol_daily": float(std),
                "conditional_mean": conditional_mean.tolist(),
            },
            seed=self.seed or 0,
        )


def build_joint_scenarios(
    spy_returns: np.ndarray,
    qqq_returns: np.ndarray,
    spy_price: float,
    qqq_price: float,
    spy_iv: float,
    qqq_iv: float,
    horizon: int,
    paths: int = 5000,
    seed: int = 42,
    lambda_: float = 0.94,
    nu: float = 5.0,
) -> Dict[str, ScenarioSet]:
    """Generate correlated SPY/QQQ scenarios preserving empirical correlation."""
    rng = np.random.default_rng(seed)

    spy_var = EWMAStudentTForecast(lambda_=lambda_, nu=nu).estimate_variance(spy_returns)
    qqq_var = EWMAStudentTForecast(lambda_=lambda_, nu=nu).estimate_variance(qqq_returns)

    min_len = min(len(spy_returns), len(qqq_returns))
    if min_len > 1:
        corr = float(np.corrcoef(spy_returns[-min_len:], qqq_returns[-min_len:])[0, 1])
    else:
        corr = 0.9
    corr = np.clip(corr, -0.99, 0.99)

    cov = np.array([[spy_var, corr * np.sqrt(spy_var * qqq_var)],
                    [corr * np.sqrt(spy_var * qqq_var), qqq_var]])
    chol = np.linalg.cholesky(cov)

    t = rng.standard_t(nu, size=(paths, horizon, 2))
    scale = np.sqrt((nu - 2) / nu)
    shocks = t * scale
    daily_returns = np.einsum("pht,td->phd", shocks, chol.T)

    spy_cum = daily_returns[:, :, 0].sum(axis=1)
    qqq_cum = daily_returns[:, :, 1].sum(axis=1)

    spy_spots = spy_price * np.exp(spy_cum)
    qqq_spots = qqq_price * np.exp(qqq_cum)

    # IV scenarios: base + random shock, weak correlation to underlying shock
    iv_shock = rng.normal(0, 0.02, size=(paths, 2))
    spy_ivs = np.clip(spy_iv + iv_shock[:, 0], 0.05, 2.0)
    qqq_ivs = np.clip(qqq_iv + iv_shock[:, 1], 0.05, 2.0)

    spy_set = ScenarioSet(
        underlying="SPY",
        horizon=horizon,
        as_of="now",
        model="M0",
        spots=spy_spots,
        ivs=spy_ivs,
        params={"lambda": lambda_, "nu": nu, "correlation": corr},
        seed=seed,
    )
    qqq_set = ScenarioSet(
        underlying="QQQ",
        horizon=horizon,
        as_of="now",
        model="M0",
        spots=qqq_spots,
        ivs=qqq_ivs,
        params={"lambda": lambda_, "nu": nu, "correlation": corr},
        seed=seed,
    )
    return {"SPY": spy_set, "QQQ": qqq_set}

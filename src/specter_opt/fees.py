"""Competition simulator fee calculations."""

from dataclasses import dataclass

from specter_opt.config import FeeConfig


@dataclass(frozen=True)
class FeeResult:
    per_contract_entry: float
    per_contract_exit: float
    total_entry: float
    total_exit: float
    min_hit: bool


def option_fees(
    quantity: int,
    premium_per_share: float,
    multiplier: int,
    config: FeeConfig,
) -> FeeResult:
    """Compute per-contract and total entry/exit fees.

    Commission depends on premium per share. Other fees are per contract per side.
    """
    if premium_per_share > config.commission_premium_threshold:
        commission = config.commission_per_contract_premium_above
    else:
        commission = config.commission_per_contract_premium_at_or_below

    per_contract_side = (
        commission
        + config.platform_per_contract
        + config.activity_per_contract
        + config.regulatory_per_contract
    )
    total_entry = max(config.min_per_order, per_contract_side * quantity)
    total_exit = max(config.min_per_order, per_contract_side * quantity)

    return FeeResult(
        per_contract_entry=per_contract_side,
        per_contract_exit=per_contract_side,
        total_entry=total_entry,
        total_exit=total_exit,
        min_hit=total_entry == config.min_per_order and quantity < 4,
    )


def round_lot_quantity(qty: float) -> int:
    """Option contracts trade in integer lots."""
    return max(0, int(round(qty)))

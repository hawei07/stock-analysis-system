"""Portfolio money, precision, and trading fee helpers."""

from decimal import Decimal, ROUND_HALF_UP


def decimal_value(value, default="0"):
    if value is None:
        value = default
    return Decimal(str(value))


def quantize(value, scale="0.0001"):
    return decimal_value(value).quantize(Decimal(scale), rounding=ROUND_HALF_UP)


def decimal_equal(left, right, scale="0.0001"):
    if left is None or right is None:
        return left is None and right is None
    return quantize(left, scale) == quantize(right, scale)


def is_domestic_market(market):
    return str(market or "").upper() in {"SH", "SZ", "BJ"}


def calculate_trade_fees(amount, trade_type, market, config):
    amount = decimal_value(amount)
    if not is_domestic_market(market):
        return {
            "commission": Decimal("0.00"),
            "stamp_tax": Decimal("0.00"),
            "transfer_fee": Decimal("0.00"),
            "total_fee": Decimal("0.00"),
        }

    commission = amount * config["commission_rate"]
    if commission > 0 and commission < config["min_commission"]:
        commission = config["min_commission"]
    stamp_tax = amount * config["stamp_tax_rate"] if trade_type == "sell" else Decimal("0")
    transfer_fee = amount * config["transfer_fee_rate"]
    commission = quantize(commission, "0.01")
    stamp_tax = quantize(stamp_tax, "0.01")
    transfer_fee = quantize(transfer_fee, "0.01")
    return {
        "commission": commission,
        "stamp_tax": stamp_tax,
        "transfer_fee": transfer_fee,
        "total_fee": commission + stamp_tax + transfer_fee,
    }

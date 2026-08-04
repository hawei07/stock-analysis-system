"""Portfolio fee configuration helpers."""

from decimal import Decimal

from services.portfolio_money import decimal_value


def fee_config(execute_query):
    rows = execute_query(
        """SELECT commission_rate, min_commission, stamp_tax_rate, transfer_fee_rate
           FROM portfolio_fee_config
           WHERE id=1"""
    )
    if not rows:
        return {
            "commission_rate": Decimal("0.000250"),
            "min_commission": Decimal("5.00"),
            "stamp_tax_rate": Decimal("0.000500"),
            "transfer_fee_rate": Decimal("0.000010"),
        }
    row = rows[0]
    return {
        "commission_rate": decimal_value(row.get("commission_rate")),
        "min_commission": decimal_value(row.get("min_commission")),
        "stamp_tax_rate": decimal_value(row.get("stamp_tax_rate")),
        "transfer_fee_rate": decimal_value(row.get("transfer_fee_rate")),
    }


def fee_config_payload(execute_query, ensure_tables):
    ensure_tables()
    config = fee_config(execute_query)
    return {
        "commission_rate": float(config["commission_rate"]),
        "min_commission": float(config["min_commission"]),
        "stamp_tax_rate": float(config["stamp_tax_rate"]),
        "transfer_fee_rate": float(config["transfer_fee_rate"]),
    }

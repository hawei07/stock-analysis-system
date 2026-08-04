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


def update_fee_config(execute_query, ensure_tables, data):
    ensure_tables()
    values = {}
    for key in ("commission_rate", "min_commission", "stamp_tax_rate", "transfer_fee_rate"):
        try:
            value = decimal_value(data.get(key))
        except Exception as exc:
            raise ValueError("费率配置必须是数字") from exc
        if value < 0:
            raise ValueError("费率配置不能小于 0")
        values[key] = value
    execute_query(
        """UPDATE portfolio_fee_config
           SET commission_rate=%s, min_commission=%s, stamp_tax_rate=%s, transfer_fee_rate=%s
           WHERE id=1""",
        (
            values["commission_rate"],
            values["min_commission"],
            values["stamp_tax_rate"],
            values["transfer_fee_rate"],
        ),
        fetch=False,
    )

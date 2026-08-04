"""Portfolio position and cost basis rebuilding."""

from decimal import Decimal

from services.portfolio_money import decimal_equal, decimal_value, quantize


def sync_cost_basis_from_trades(execute_query):
    trade_rows = execute_query(
        """SELECT id, stock_code, trade_date, trade_type, shares, price, amount,
                  commission, stamp_tax, transfer_fee, total_fee, cash_delta,
                  shares_before, shares_after, cost_price_before, cost_price_after, realized_profit
           FROM portfolio_trades
           WHERE is_void=0
           ORDER BY stock_code, trade_date, id"""
    )
    action_rows = execute_query(
        """SELECT id, action_date, stock_code, action_type, cash_amount, shares, price, amount, cash_delta,
                  shares_before, shares_after, cost_price_before, cost_price_after, note
           FROM portfolio_corporate_actions
           WHERE is_void=0
           ORDER BY stock_code, action_date, id"""
    )
    if not trade_rows and not action_rows:
        return False

    changed = False
    grouped = {}
    for row in trade_rows:
        item = dict(row)
        item["_kind"] = "trade"
        item["_date"] = row["trade_date"]
        grouped.setdefault(row["stock_code"], []).append(item)
    for row in action_rows:
        item = dict(row)
        item["_kind"] = "action"
        item["_date"] = row["action_date"]
        grouped.setdefault(row["stock_code"], []).append(item)

    for code, items in grouped.items():
        items.sort(key=lambda item: (item["_date"], 0 if item["_kind"] == "trade" else 1, item["id"]))
        first = items[0]
        shares = decimal_value(first.get("shares_before"))
        cost = decimal_value(first.get("cost_price_before")) if first.get("cost_price_before") is not None else None
        if cost is None and shares == 0:
            cost = Decimal("0")
        if cost is None:
            continue

        for item in items:
            before_shares = shares
            before_cost = cost if before_shares > 0 else None
            realized_profit = None
            next_cash_delta = Decimal("0.00")

            if item["_kind"] == "trade":
                trade_shares = decimal_value(item["shares"])
                amount = decimal_value(item["amount"])
                total_fee = decimal_value(item.get("total_fee"))
                cash_delta = decimal_value(item.get("cash_delta")) if item.get("cash_delta") is not None else None
                if item["trade_type"] == "buy":
                    buy_cost = amount + total_fee
                    shares = before_shares + trade_shares
                    cost = ((before_shares * cost) + buy_cost) / shares if before_shares > 0 and shares > 0 else buy_cost / trade_shares
                    next_cash_delta = -buy_cost
                else:
                    if before_cost is None:
                        break
                    sell_proceeds = amount - total_fee
                    realized_profit = sell_proceeds - (before_cost * trade_shares)
                    shares = before_shares - trade_shares
                    cost = ((before_shares * before_cost) - sell_proceeds) / shares if shares > 0 else None
                    next_cash_delta = sell_proceeds

                trade_changed = (
                    not decimal_equal(item.get("shares_before"), before_shares)
                    or not decimal_equal(item.get("shares_after"), shares)
                    or not decimal_equal(item.get("cost_price_before"), before_cost)
                    or not decimal_equal(item.get("cost_price_after"), cost)
                    or not decimal_equal(item.get("realized_profit"), realized_profit, "0.01")
                    or not decimal_equal(cash_delta, next_cash_delta, "0.01")
                )
                if trade_changed:
                    execute_query(
                        """UPDATE portfolio_trades
                           SET shares_before=%s, shares_after=%s,
                               cost_price_before=%s, cost_price_after=%s, realized_profit=%s,
                               cash_delta=%s
                           WHERE id=%s""",
                        (
                            quantize(before_shares),
                            quantize(shares),
                            quantize(before_cost) if before_cost is not None else None,
                            quantize(cost) if cost is not None else None,
                            quantize(realized_profit, "0.01") if realized_profit is not None else None,
                            quantize(next_cash_delta, "0.01"),
                            item["id"],
                        ),
                        fetch=False,
                    )
                    changed = True
                continue

            action_type = item["action_type"]
            if before_cost is None:
                break
            if action_type == "cash_dividend":
                cash_amount = decimal_value(item["cash_amount"])
                shares = before_shares
                cost = ((before_shares * before_cost) - cash_amount) / shares if shares > 0 else None
                next_cash_delta = cash_amount
            elif action_type == "bonus_share":
                bonus_shares = decimal_value(item["shares"])
                shares = before_shares + bonus_shares
                cost = (before_shares * before_cost) / shares if shares > 0 else None
            elif action_type == "rights_issue":
                issue_shares = decimal_value(item["shares"])
                amount = decimal_value(item["amount"])
                shares = before_shares + issue_shares
                cost = ((before_shares * before_cost) + amount) / shares if shares > 0 else None
                next_cash_delta = -amount
            else:
                continue

            action_changed = (
                not decimal_equal(item.get("shares_before"), before_shares)
                or not decimal_equal(item.get("shares_after"), shares)
                or not decimal_equal(item.get("cost_price_before"), before_cost)
                or not decimal_equal(item.get("cost_price_after"), cost)
                or not decimal_equal(item.get("cash_delta"), next_cash_delta, "0.01")
            )
            if action_changed:
                execute_query(
                    """UPDATE portfolio_corporate_actions
                       SET shares_before=%s, shares_after=%s,
                           cost_price_before=%s, cost_price_after=%s, cash_delta=%s
                       WHERE id=%s""",
                    (
                        quantize(before_shares),
                        quantize(shares),
                        quantize(before_cost) if before_cost is not None else None,
                        quantize(cost) if cost is not None else None,
                        quantize(next_cash_delta, "0.01"),
                        item["id"],
                    ),
                    fetch=False,
                )
                changed = True

        position_rows = execute_query(
            "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
            (code,),
        )
        if shares > 0:
            if position_rows:
                current = position_rows[0]
                position_changed = (
                    not decimal_equal(current.get("shares"), shares)
                    or not decimal_equal(current.get("cost_price"), cost)
                )
                if position_changed:
                    execute_query(
                        "UPDATE portfolio_positions SET shares=%s, cost_price=%s, updated_at=CURRENT_TIMESTAMP WHERE stock_code=%s",
                        (quantize(shares), quantize(cost) if cost is not None else None, code),
                        fetch=False,
                    )
                    changed = True
            else:
                execute_query(
                    "INSERT INTO portfolio_positions (stock_code, shares, cost_price) VALUES (%s, %s, %s)",
                    (code, quantize(shares), quantize(cost) if cost is not None else None),
                    fetch=False,
                )
                changed = True
        elif position_rows:
            execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)
            changed = True

    return changed

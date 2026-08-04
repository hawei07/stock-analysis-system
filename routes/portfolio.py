"""Portfolio page and API routes."""

from decimal import Decimal

from flask import jsonify, render_template, request
from services import portfolio_cash
from services import portfolio_nav


def register_portfolio_routes(app, deps):
    execute_query = deps["execute_query"]
    _execute_insert_id = deps["execute_insert_id"]
    _ensure_portfolio_tables = deps["ensure_portfolio_tables"]
    _portfolio_current_state = deps["portfolio_current_state"]
    _portfolio_fee_config_payload = deps["portfolio_fee_config_payload"]
    _decimal_value = deps["decimal_value"]
    _quantize = deps["quantize"]
    _latest_dividend_per_share = deps["latest_dividend_per_share"]
    _currency_for_market = deps["currency_for_market"]
    _portfolio_trades_payload = deps["portfolio_trades_payload"]
    _portfolio_actions_payload = deps["portfolio_actions_payload"]
    _portfolio_audit_payload = deps["portfolio_audit_payload"]
    _sync_portfolio_cost_basis_from_trades = deps["sync_portfolio_cost_basis_from_trades"]
    _portfolio_rebuilt_cash_amount = deps["portfolio_rebuilt_cash_amount"]
    _save_portfolio_snapshot = deps["save_portfolio_snapshot"]
    _portfolio_flows_payload = deps["portfolio_flows_payload"]
    _resolve_portfolio_stock = deps["resolve_portfolio_stock"]
    _calculate_portfolio_trade_fees = deps["calculate_portfolio_trade_fees"]
    _portfolio_cash_amount = deps["portfolio_cash_amount"]
    _void_linked_cash_flow = deps["void_linked_cash_flow"]

    @app.route("/portfolio")
    def portfolio_page():
        return render_template("portfolio.html")

    @app.route("/api/portfolio", methods=["GET"])
    def api_portfolio_get():
        return jsonify(_portfolio_current_state())


    @app.route("/api/portfolio/fee-config", methods=["GET"])
    def api_portfolio_fee_config():
        return jsonify(_portfolio_fee_config_payload())


    @app.route("/api/portfolio/fee-config", methods=["PUT"])
    def api_portfolio_update_fee_config():
        _ensure_portfolio_tables()
        data = request.get_json(force=True)
        values = {}
        for key in ("commission_rate", "min_commission", "stamp_tax_rate", "transfer_fee_rate"):
            try:
                value = _decimal_value(data.get(key))
            except Exception:
                return jsonify({"error": "费率配置必须是数字"}), 400
            if value < 0:
                return jsonify({"error": "费率配置不能小于 0"}), 400
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
        return jsonify({"ok": True, **_portfolio_fee_config_payload()})


    @app.route("/api/portfolio/positions", methods=["POST"])
    def api_portfolio_save_position():
        return jsonify({"error": "持仓只能通过买入/卖出交易变动，不能直接录入或修改"}), 400


    @app.route("/api/portfolio/positions/<code>", methods=["GET"])
    def api_portfolio_position_get(code):
        _ensure_portfolio_tables()
        rows = execute_query(
            """SELECT p.stock_code, p.shares, p.cost_price, p.custom_dividend_per_share,
                      s.name, s.market, s.industry
               FROM portfolio_positions p
               JOIN stocks s ON s.code = p.stock_code
               WHERE p.stock_code=%s
               LIMIT 1""",
            (code,),
        )
        if not rows:
            return jsonify({"ok": True, "held": False, "code": code})

        r = rows[0]
        shares = float(r["shares"])
        dividends = _latest_dividend_per_share([code]).get(code, {})
        custom_dividend = float(r["custom_dividend_per_share"]) if r.get("custom_dividend_per_share") is not None else None
        auto_dividend = dividends.get("dividend_per_share")
        dividend_per_share = custom_dividend if custom_dividend is not None else auto_dividend
        return jsonify({
            "ok": True,
            "held": True,
            "code": r["stock_code"],
            "name": r["name"],
            "market": r["market"],
            "industry": r.get("industry"),
            "shares": shares,
            "cost_price": round(float(r["cost_price"]), 4) if r.get("cost_price") is not None else None,
            "cost_price_currency": _currency_for_market(r.get("market")),
            "custom_dividend_per_share": round(custom_dividend, 2) if custom_dividend is not None else None,
            "auto_dividend_per_share": round(auto_dividend, 3) if auto_dividend is not None else None,
            "dividend_per_share": round(dividend_per_share, 2) if dividend_per_share is not None else None,
            "dividend_year": dividends.get("fiscal_year"),
            "dividend_source": "custom" if custom_dividend is not None else "auto",
        })


    @app.route("/api/portfolio/positions/<code>", methods=["DELETE"])
    def api_portfolio_delete_position(code):
        return jsonify({"error": "持仓只能通过买入/卖出交易变动，不能直接删除"}), 400


    @app.route("/api/portfolio/trades", methods=["GET"])
    def api_portfolio_trades():
        return jsonify(_portfolio_trades_payload())


    @app.route("/api/portfolio/actions", methods=["GET"])
    def api_portfolio_actions():
        return jsonify(_portfolio_actions_payload())


    @app.route("/api/portfolio/audit", methods=["GET"])
    def api_portfolio_audit():
        return jsonify(_portfolio_audit_payload())


    @app.route("/api/portfolio/rebuild", methods=["POST"])
    def api_portfolio_rebuild():
        _ensure_portfolio_tables()
        _sync_portfolio_cost_basis_from_trades()
        rebuilt_cash = _portfolio_rebuilt_cash_amount()
        portfolio_cash.set_cash_amount(execute_query, rebuilt_cash)
        state = _save_portfolio_snapshot()
        state["audit"] = _portfolio_audit_payload()
        state["trades"] = _portfolio_trades_payload()
        state["actions"] = _portfolio_actions_payload()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/trades", methods=["POST"])
    def api_portfolio_add_trade():
        _ensure_portfolio_tables()
        data = request.get_json(force=True)
        trade_date = str(data.get("trade_date") or datetime.now().date()).strip()
        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "日期格式必须是 YYYY-MM-DD"}), 400

        trade_type = str(data.get("trade_type") or "").strip().lower()
        if trade_type not in ("buy", "sell"):
            return jsonify({"error": "交易方向必须是买入或卖出"}), 400

        stock = _resolve_portfolio_stock(str(data.get("code", data.get("identifier", ""))).strip())
        if not stock:
            return jsonify({"error": "未找到匹配的股票，请输入代码或更准确的名称"}), 404
        code = stock["code"]

        try:
            shares = float(data.get("shares"))
        except (TypeError, ValueError):
            return jsonify({"error": "交易股数必须是数字"}), 400
        if shares <= 0:
            return jsonify({"error": "交易股数必须大于 0"}), 400

        try:
            price = float(data.get("price"))
        except (TypeError, ValueError):
            return jsonify({"error": "成交价必须是数字"}), 400
        if price <= 0:
            return jsonify({"error": "成交价必须大于 0"}), 400

        note = str(data.get("note") or "").strip()[:255]
        position_rows = execute_query(
            "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
            (code,),
        )
        old_shares = float(position_rows[0]["shares"]) if position_rows else 0.0
        old_cost = float(position_rows[0]["cost_price"]) if position_rows and position_rows[0].get("cost_price") is not None else None

        amount = shares * price
        amount_dec = _quantize(amount, "0.01")
        fees = _calculate_portfolio_trade_fees(amount_dec, trade_type, stock.get("market"))
        total_fee = fees["total_fee"]
        cash_delta_dec = -(amount_dec + total_fee) if trade_type == "buy" else amount_dec - total_fee
        cash_delta = float(cash_delta_dec)
        cash_amount = _portfolio_cash_amount()
        new_cash = cash_amount + cash_delta
        if new_cash < 0:
            return jsonify({"error": "现金不足，无法买入"}), 400

        realized_profit = None
        if trade_type == "buy":
            if old_shares > 0 and old_cost is None:
                return jsonify({"error": "这只股票已有持仓但缺少历史成本，无法继续自动计算成本价"}), 400
            new_shares = old_shares + shares
            buy_cost = float(amount_dec + total_fee)
            new_cost = ((old_shares * old_cost) + buy_cost) / new_shares if old_shares > 0 else buy_cost / shares
            execute_query(
                """INSERT INTO portfolio_positions (stock_code, shares, cost_price)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE shares=VALUES(shares), cost_price=VALUES(cost_price), updated_at=CURRENT_TIMESTAMP""",
                (code, round(new_shares, 4), round(new_cost, 4)),
                fetch=False,
            )
        else:
            if old_shares <= 0:
                return jsonify({"error": "当前没有这只股票的持仓，无法卖出"}), 400
            if shares > old_shares:
                return jsonify({"error": f"卖出股数不能超过当前持仓 {old_shares:g} 股"}), 400
            new_shares = old_shares - shares
            sell_proceeds = float(amount_dec - total_fee)
            realized_profit = sell_proceeds - (old_cost * shares) if old_cost is not None else None
            new_cost = ((old_shares * old_cost) - sell_proceeds) / new_shares if new_shares > 0 and old_cost is not None else None
            if new_shares > 0:
                execute_query(
                    "UPDATE portfolio_positions SET shares=%s, cost_price=%s, updated_at=CURRENT_TIMESTAMP WHERE stock_code=%s",
                    (round(new_shares, 4), round(new_cost, 4) if new_cost is not None else None, code),
                    fetch=False,
                )
            else:
                execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)

        trade_id = _execute_insert_id(
            """INSERT INTO portfolio_trades
               (trade_date, stock_code, trade_type, shares, price, amount,
                commission, stamp_tax, transfer_fee, total_fee, cash_delta,
                shares_before, shares_after, cost_price_before, cost_price_after, realized_profit, note)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                trade_date,
                code,
                trade_type,
                round(shares, 4),
                round(price, 4),
                round(amount, 2),
                fees["commission"],
                fees["stamp_tax"],
                fees["transfer_fee"],
                fees["total_fee"],
                cash_delta_dec,
                round(old_shares, 4),
                round(new_shares, 4),
                round(old_cost, 4) if old_cost is not None else None,
                round(new_cost, 4) if new_cost is not None else None,
                round(realized_profit, 2) if realized_profit is not None else None,
                note,
            ),
        )
        flow_note = note or f"{stock['name']}({code}) {'买入' if trade_type == 'buy' else '卖出'}"
        execute_query(
            """INSERT INTO portfolio_cash_flows
               (flow_date, amount, flow_source, source_type, source_id, note)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (trade_date, cash_delta_dec, "trade", "trade", trade_id, flow_note[:255]),
            fetch=False,
        )
        execute_query(
            "UPDATE portfolio_cash SET amount=%s WHERE id=1",
            (round(new_cash, 2),),
            fetch=False,
        )
        state = _save_portfolio_snapshot()
        state["trades"] = _portfolio_trades_payload()
        state["actions"] = _portfolio_actions_payload()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/trades/<int:trade_id>/void", methods=["POST"])
    def api_portfolio_void_trade(trade_id):
        _ensure_portfolio_tables()
        data = request.get_json(silent=True) or {}
        void_note = str(data.get("void_note") or "作废交易").strip()[:255]
        rows = execute_query(
            """SELECT id, trade_date, stock_code, cash_delta, is_void
               FROM portfolio_trades
               WHERE id=%s
               LIMIT 1""",
            (trade_id,),
        )
        if not rows:
            return jsonify({"error": "未找到这笔交易"}), 404
        row = rows[0]
        if row.get("is_void"):
            return jsonify({"error": "这笔交易已作废"}), 400
        execute_query(
            "UPDATE portfolio_trades SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note=%s WHERE id=%s",
            (void_note, trade_id),
            fetch=False,
        )
        voided_flow_amount = _void_linked_cash_flow(
            "trade",
            trade_id,
            "trade",
            row["trade_date"],
            row["cash_delta"],
            row["stock_code"],
            void_note,
        )
        if voided_flow_amount != 0:
            current_cash = _decimal_value(_portfolio_cash_amount())
            execute_query(
                "UPDATE portfolio_cash SET amount=%s WHERE id=1",
                (_quantize(current_cash - voided_flow_amount, "0.01"),),
                fetch=False,
            )
        _sync_portfolio_cost_basis_from_trades()
        state = _save_portfolio_snapshot()
        state["audit"] = _portfolio_audit_payload()
        state["trades"] = _portfolio_trades_payload()
        state["actions"] = _portfolio_actions_payload()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/actions", methods=["POST"])
    def api_portfolio_add_corporate_action():
        _ensure_portfolio_tables()
        data = request.get_json(force=True)
        action_date = str(data.get("action_date") or datetime.now().date()).strip()
        try:
            datetime.strptime(action_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "日期格式必须是 YYYY-MM-DD"}), 400

        action_type = str(data.get("action_type") or "").strip().lower()
        if action_type not in ("cash_dividend", "bonus_share", "rights_issue"):
            return jsonify({"error": "权益类型必须是现金分红、送股/转增或配股"}), 400

        stock = _resolve_portfolio_stock(str(data.get("code", data.get("identifier", ""))).strip())
        if not stock:
            return jsonify({"error": "未找到匹配的股票，请输入代码或更准确的名称"}), 404
        code = stock["code"]

        position_rows = execute_query(
            "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
            (code,),
        )
        if not position_rows:
            return jsonify({"error": "当前没有这只股票的持仓，无法记录权益事件"}), 400
        old_shares = _decimal_value(position_rows[0]["shares"])
        old_cost = _decimal_value(position_rows[0]["cost_price"]) if position_rows[0].get("cost_price") is not None else None
        if old_shares <= 0 or old_cost is None:
            return jsonify({"error": "这只股票缺少有效持仓或成本，无法记录权益事件"}), 400

        note = str(data.get("note") or "").strip()[:255]
        cash_amount = Decimal("0.00")
        action_shares = Decimal("0.0000")
        price = None
        amount = Decimal("0.00")
        cash_delta = Decimal("0.00")
        new_shares = old_shares
        new_cost = old_cost

        if action_type == "cash_dividend":
            raw_cash = data.get("cash_amount")
            if raw_cash in (None, ""):
                try:
                    cash_amount = _decimal_value(data.get("dividend_per_share")) * old_shares
                except Exception:
                    return jsonify({"error": "现金分红金额必须是数字"}), 400
            else:
                try:
                    cash_amount = _decimal_value(raw_cash)
                except Exception:
                    return jsonify({"error": "现金分红金额必须是数字"}), 400
            if cash_amount <= 0:
                return jsonify({"error": "现金分红金额必须大于 0"}), 400
            cash_amount = _quantize(cash_amount, "0.01")
            amount = cash_amount
            cash_delta = cash_amount
            new_cost = ((old_shares * old_cost) - cash_amount) / old_shares
        elif action_type == "bonus_share":
            try:
                action_shares = _decimal_value(data.get("shares"))
            except Exception:
                return jsonify({"error": "送股/转增股数必须是数字"}), 400
            if action_shares <= 0:
                return jsonify({"error": "送股/转增股数必须大于 0"}), 400
            new_shares = old_shares + action_shares
            new_cost = (old_shares * old_cost) / new_shares
        else:
            try:
                action_shares = _decimal_value(data.get("shares"))
                price = _decimal_value(data.get("price"))
            except Exception:
                return jsonify({"error": "配股股数和价格必须是数字"}), 400
            if action_shares <= 0:
                return jsonify({"error": "配股股数必须大于 0"}), 400
            if price < 0:
                return jsonify({"error": "配股价格不能小于 0"}), 400
            amount = _quantize(action_shares * price, "0.01")
            cash_delta = -amount
            cash_amount_now = _decimal_value(_portfolio_cash_amount())
            if cash_amount_now + cash_delta < 0:
                return jsonify({"error": "现金不足，无法记录配股"}), 400
            new_shares = old_shares + action_shares
            new_cost = ((old_shares * old_cost) + amount) / new_shares

        action_id = _execute_insert_id(
            """INSERT INTO portfolio_corporate_actions
               (action_date, stock_code, action_type, cash_amount, shares, price, amount, cash_delta,
                shares_before, shares_after, cost_price_before, cost_price_after, note)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                action_date,
                code,
                action_type,
                cash_amount,
                _quantize(action_shares),
                _quantize(price) if price is not None else None,
                amount,
                cash_delta,
                _quantize(old_shares),
                _quantize(new_shares),
                _quantize(old_cost),
                _quantize(new_cost) if new_cost is not None else None,
                note,
            ),
        )
        if new_shares > 0:
            execute_query(
                "UPDATE portfolio_positions SET shares=%s, cost_price=%s, updated_at=CURRENT_TIMESTAMP WHERE stock_code=%s",
                (_quantize(new_shares), _quantize(new_cost) if new_cost is not None else None, code),
                fetch=False,
            )
        else:
            execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)

        if cash_delta != 0:
            cash_amount_now = _decimal_value(_portfolio_cash_amount())
            execute_query(
                "UPDATE portfolio_cash SET amount=%s WHERE id=1",
                (_quantize(cash_amount_now + cash_delta, "0.01"),),
                fetch=False,
            )
            flow_label = {"cash_dividend": "分红到账", "rights_issue": "配股扣款"}.get(action_type, "权益现金")
            flow_note = note or f"{stock['name']}({code}) {flow_label}"
            execute_query(
                """INSERT INTO portfolio_cash_flows
                   (flow_date, amount, flow_source, source_type, source_id, note)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (action_date, _quantize(cash_delta, "0.01"), "action", "action", action_id, flow_note[:255]),
                fetch=False,
            )

        state = _save_portfolio_snapshot()
        state["trades"] = _portfolio_trades_payload()
        state["actions"] = _portfolio_actions_payload()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/actions/<int:action_id>/void", methods=["POST"])
    def api_portfolio_void_corporate_action(action_id):
        _ensure_portfolio_tables()
        data = request.get_json(silent=True) or {}
        void_note = str(data.get("void_note") or "作废权益事件").strip()[:255]
        rows = execute_query(
            """SELECT id, action_date, stock_code, cash_delta, is_void
               FROM portfolio_corporate_actions
               WHERE id=%s
               LIMIT 1""",
            (action_id,),
        )
        if not rows:
            return jsonify({"error": "未找到这笔权益记录"}), 404
        row = rows[0]
        if row.get("is_void"):
            return jsonify({"error": "这笔权益记录已作废"}), 400
        execute_query(
            "UPDATE portfolio_corporate_actions SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note=%s WHERE id=%s",
            (void_note, action_id),
            fetch=False,
        )
        voided_flow_amount = _void_linked_cash_flow(
            "action",
            action_id,
            "action",
            row["action_date"],
            row["cash_delta"],
            row["stock_code"],
            void_note,
        )
        if voided_flow_amount != 0:
            current_cash = _decimal_value(_portfolio_cash_amount())
            execute_query(
                "UPDATE portfolio_cash SET amount=%s WHERE id=1",
                (_quantize(current_cash - voided_flow_amount, "0.01"),),
                fetch=False,
            )
        _sync_portfolio_cost_basis_from_trades()
        state = _save_portfolio_snapshot()
        state["audit"] = _portfolio_audit_payload()
        state["trades"] = _portfolio_trades_payload()
        state["actions"] = _portfolio_actions_payload()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/positions/<code>/dividend", methods=["PUT"])
    def api_portfolio_update_dividend(code):
        _ensure_portfolio_tables()
        data = request.get_json(force=True)
        value = data.get("dividend_per_share")
        try:
            value = _quantize(value, "0.01")
        except Exception:
            return jsonify({"error": "每股分红必须是数字"}), 400
        if value < 0:
            return jsonify({"error": "每股分红不能小于 0"}), 400
        rows = execute_query("SELECT id FROM portfolio_positions WHERE stock_code=%s", (code,))
        if not rows:
            return jsonify({"error": "持仓中没有这只股票"}), 404
        execute_query(
            "UPDATE portfolio_positions SET custom_dividend_per_share=%s WHERE stock_code=%s",
            (value, code),
            fetch=False,
        )
        return jsonify({"ok": True, **_save_portfolio_snapshot()})


    @app.route("/api/portfolio/positions/<code>/dividend/reset", methods=["POST"])
    def api_portfolio_reset_dividend(code):
        _ensure_portfolio_tables()
        position_rows = execute_query("SELECT id FROM portfolio_positions WHERE stock_code=%s", (code,))
        if not position_rows:
            return jsonify({"error": "持仓中没有这只股票"}), 404
        execute_query(
            "UPDATE portfolio_positions SET custom_dividend_per_share=NULL WHERE stock_code=%s",
            (code,),
            fetch=False,
        )
        state = _save_portfolio_snapshot()
        reset_row = next((p for p in state["positions"] if p["code"] == code), None)
        if reset_row:
            state["reset_to"] = {
                "fiscal_year": reset_row.get("dividend_year"),
                "dividend_per_share": reset_row.get("auto_dividend_per_share"),
            }
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/cash", methods=["PUT"])
    def api_portfolio_update_cash():
        return jsonify({"error": "现金只能通过资金流水入金/出金变动"}), 400


    @app.route("/api/portfolio/flows", methods=["GET"])
    def api_portfolio_flows():
        return jsonify(_portfolio_flows_payload())


    @app.route("/api/portfolio/flows", methods=["POST"])
    def api_portfolio_add_flow():
        data = request.get_json(force=True)
        try:
            portfolio_cash.add_external_flow(
                execute_query,
                _ensure_portfolio_tables,
                _portfolio_cash_amount,
                data.get("flow_date"),
                data.get("amount"),
                data.get("note"),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        state = _save_portfolio_snapshot()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/flows/<int:flow_id>", methods=["DELETE"])
    def api_portfolio_delete_flow(flow_id):
        try:
            portfolio_cash.void_external_flow(
                execute_query,
                _ensure_portfolio_tables,
                _portfolio_cash_amount,
                flow_id,
            )
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        state = _save_portfolio_snapshot()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/snapshot", methods=["POST"])
    def api_portfolio_snapshot():
        return jsonify({"ok": True, **_save_portfolio_snapshot()})


    @app.route("/api/portfolio/nav")
    def api_portfolio_nav():
        return jsonify(portfolio_nav.history(
            execute_query,
            _ensure_portfolio_tables,
            _portfolio_current_state,
            include_live=request.args.get("live") == "1",
        ))

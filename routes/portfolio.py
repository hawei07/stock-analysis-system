"""Portfolio page and API routes."""

from flask import jsonify, render_template, request
from services import portfolio_actions
from services import portfolio_cash
from services import portfolio_nav
from services import portfolio_trades


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
        data = request.get_json(force=True)
        try:
            portfolio_trades.add_trade(
                execute_query,
                _execute_insert_id,
                _ensure_portfolio_tables,
                _resolve_portfolio_stock,
                _calculate_portfolio_trade_fees,
                _portfolio_cash_amount,
                data,
            )
        except portfolio_trades.PortfolioTradeError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        state = _save_portfolio_snapshot()
        state["trades"] = _portfolio_trades_payload()
        state["actions"] = _portfolio_actions_payload()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/trades/<int:trade_id>/void", methods=["POST"])
    def api_portfolio_void_trade(trade_id):
        data = request.get_json(silent=True) or {}
        try:
            portfolio_trades.void_trade(
                execute_query,
                _void_linked_cash_flow,
                _sync_portfolio_cost_basis_from_trades,
                _portfolio_cash_amount,
                trade_id,
                data.get("void_note"),
            )
        except portfolio_trades.PortfolioTradeError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        state = _save_portfolio_snapshot()
        state["audit"] = _portfolio_audit_payload()
        state["trades"] = _portfolio_trades_payload()
        state["actions"] = _portfolio_actions_payload()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/actions", methods=["POST"])
    def api_portfolio_add_corporate_action():
        data = request.get_json(force=True)
        try:
            portfolio_actions.add_corporate_action(
                execute_query,
                _execute_insert_id,
                _ensure_portfolio_tables,
                _resolve_portfolio_stock,
                _portfolio_cash_amount,
                data,
            )
        except portfolio_actions.PortfolioActionError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        state = _save_portfolio_snapshot()
        state["trades"] = _portfolio_trades_payload()
        state["actions"] = _portfolio_actions_payload()
        state["flows"] = _portfolio_flows_payload()
        return jsonify({"ok": True, **state})


    @app.route("/api/portfolio/actions/<int:action_id>/void", methods=["POST"])
    def api_portfolio_void_corporate_action(action_id):
        data = request.get_json(silent=True) or {}
        try:
            portfolio_actions.void_corporate_action(
                execute_query,
                _void_linked_cash_flow,
                _sync_portfolio_cost_basis_from_trades,
                _portfolio_cash_amount,
                action_id,
                data.get("void_note"),
            )
        except portfolio_actions.PortfolioActionError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
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

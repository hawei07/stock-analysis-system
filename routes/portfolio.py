"""Portfolio page and API routes."""

from flask import jsonify, render_template, request
from services import portfolio_actions
from services import portfolio_cash
from services import portfolio_fees
from services import portfolio_nav
from services import portfolio_position_detail
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
        data = request.get_json(force=True)
        try:
            portfolio_fees.update_fee_config(execute_query, _ensure_portfolio_tables, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, **_portfolio_fee_config_payload()})


    @app.route("/api/portfolio/positions", methods=["POST"])
    def api_portfolio_save_position():
        return jsonify({"error": "\u6301\u4ed3\u53ea\u80fd\u901a\u8fc7\u4e70\u5165/\u5356\u51fa\u4ea4\u6613\u53d8\u52a8\uff0c\u4e0d\u80fd\u76f4\u63a5\u5f55\u5165\u6216\u4fee\u6539"}), 400


    @app.route("/api/portfolio/positions/<code>", methods=["GET"])
    def api_portfolio_position_get(code):
        return jsonify(portfolio_position_detail.position_detail(
            execute_query,
            _ensure_portfolio_tables,
            _latest_dividend_per_share,
            _currency_for_market,
            code,
        ))


    @app.route("/api/portfolio/positions/<code>", methods=["DELETE"])
    def api_portfolio_delete_position(code):
        return jsonify({"error": "\u6301\u4ed3\u53ea\u80fd\u901a\u8fc7\u4e70\u5165/\u5356\u51fa\u4ea4\u6613\u53d8\u52a8\uff0c\u4e0d\u80fd\u76f4\u63a5\u5220\u9664"}), 400


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
        data = request.get_json(force=True)
        try:
            portfolio_position_detail.update_custom_dividend(
                execute_query,
                _ensure_portfolio_tables,
                code,
                data.get("dividend_per_share"),
            )
        except portfolio_position_detail.PortfolioPositionError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        return jsonify({"ok": True, **_save_portfolio_snapshot()})


    @app.route("/api/portfolio/positions/<code>/dividend/reset", methods=["POST"])
    def api_portfolio_reset_dividend(code):
        try:
            portfolio_position_detail.reset_custom_dividend(execute_query, _ensure_portfolio_tables, code)
        except portfolio_position_detail.PortfolioPositionError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
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
        return jsonify({"error": "\u73b0\u91d1\u53ea\u80fd\u901a\u8fc7\u8d44\u91d1\u6d41\u6c34\u5165\u91d1/\u51fa\u91d1\u53d8\u52a8"}), 400


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

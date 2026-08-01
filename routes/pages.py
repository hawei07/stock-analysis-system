"""Page routes."""

from flask import render_template


def register_page_routes(app):
    @app.route("/")
    @app.route("/stock/<code>")
    def index(code=None):
        return render_template("index.html")

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, render_template

from . import admin, auth, catalog, customer, db, employee, security
from .services import analytics, bootstrap, etl


def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parents[1]
    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me-before-deploy"),
        PROJECT_ROOT=project_root,
        DATA_DIR=project_root / "data",
        INSTANCE_DIR=project_root / "instance",
        OLTP_DATABASE=project_root / "instance" / "oltp.db",
        STAGING_DATABASE=project_root / "instance" / "staging.db",
        DWH_DATABASE=project_root / "instance" / "dwh.db",
        PRODUCTS_PER_PAGE=24,
    )

    if test_config:
        app.config.update(test_config)

    instance_dir = Path(app.config["INSTANCE_DIR"])
    instance_dir.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    security.init_app(app)
    auth.init_app(app)
    bootstrap.init_app(app)
    etl.init_app(app)
    analytics.init_app(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(catalog.bp)
    app.register_blueprint(customer.bp)
    app.register_blueprint(employee.bp)
    app.register_blueprint(admin.bp)

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.template_filter("money")
    def money(value):
        try:
            return f"VND {float(value):,.0f}"
        except (TypeError, ValueError):
            return "VND 0"

    @app.template_filter("datetime_en")
    def datetime_en(value):
        if not value:
            return "—"
        return str(value).replace("T", " ")[:16]

    return app


from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from flask import current_app, g


DATABASE_KEYS = {
    "oltp": "OLTP_DATABASE",
    "staging": "STAGING_DATABASE",
    "dwh": "DWH_DATABASE",
}


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def get_db(name: str = "oltp") -> sqlite3.Connection:
    if name not in DATABASE_KEYS:
        raise KeyError(f"Unknown database: {name}")
    cache_key = f"db_{name}"
    connection = getattr(g, cache_key, None)
    if connection is None:
        connection = _connect(Path(current_app.config[DATABASE_KEYS[name]]))
        setattr(g, cache_key, connection)
    return connection


def close_db(_error=None) -> None:
    for name in DATABASE_KEYS:
        cache_key = f"db_{name}"
        connection = getattr(g, cache_key, None)
        if connection is not None:
            connection.close()
            delattr(g, cache_key)


def execute_script(name: str, script_name: str) -> None:
    script_path = Path(current_app.config["PROJECT_ROOT"]) / "sql" / script_name
    get_db(name).executescript(script_path.read_text(encoding="utf-8"))


def table_exists(name: str, table_name: str) -> bool:
    row = get_db(name).execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone()
    return row is not None


@click.command("db-status")
def db_status_command() -> None:
    for name, config_key in DATABASE_KEYS.items():
        path = Path(current_app.config[config_key])
        click.echo(f"{name}: {'ready' if path.exists() else 'missing'} - {path}")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(db_status_command)


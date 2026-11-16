from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from flask import current_app, g

from . import sqlserver

DATABASE_ERRORS = (sqlite3.Error, sqlserver.DatabaseError)

DATABASE_KEYS = {
    "oltp": "OLTP_DATABASE",
    "staging": "STAGING_DATABASE",
    "dwh": "DWH_DATABASE",
}


def sqlserver_enabled():
    return bool(current_app.config["SQLSERVER_CONNECTION"])


def sqlserver_name(name):
    database = current_app.config[f"SQLSERVER_{name.upper()}"]
    if not database or not database.isascii() or not database.replace("_", "").isalnum() or len(database) > 128:
        raise ValueError("SQL Server database names must use letters, digits, or underscores")
    return database


def connect_sqlserver(database):
    connection = current_app.config["SQLSERVER_CONNECTION"].rstrip(";")
    return sqlserver.connect(f"{connection};DATABASE={database};")


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
        if sqlserver_enabled():
            connection = connect_sqlserver(sqlserver_name(name))
        else:
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
    directory = Path(current_app.config["PROJECT_ROOT"]) / "sql"
    if sqlserver_enabled():
        directory /= "sqlserver"
    script_path = directory / script_name
    get_db(name).executescript(script_path.read_text(encoding="utf-8"))


def table_exists(name: str, table_name: str) -> bool:
    if sqlserver_enabled():
        statement = "SELECT 1 FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo') AND name = ?"
    else:
        statement = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return get_db(name).execute(statement, (table_name,)).fetchone() is not None


@click.command("db-status")
def db_status_command() -> None:
    required_tables = {"oltp": "users", "staging": "etl_batch", "dwh": "fact_sales"}
    for name, config_key in DATABASE_KEYS.items():
        if sqlserver_enabled():
            database_name = get_db(name).execute("SELECT DB_NAME()").fetchone()[0]
            if not table_exists(name, required_tables[name]):
                raise click.ClickException(f"{database_name} needs the QuocDat schema. Run migrate-sqlserver.")
            click.echo(f"{name}: connected - {database_name}")
            continue
        path = Path(current_app.config[config_key])
        click.echo(f"{name}: {'ready' if path.exists() else 'missing'} - {path}")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(db_status_command)


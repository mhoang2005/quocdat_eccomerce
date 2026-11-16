"""Transfer the three SQLite databases into empty SQL Server databases."""

from contextlib import ExitStack, closing
import json
import re
import sqlite3
from pathlib import Path

import click
from flask import current_app

from app.db import DATABASE_KEYS, connect_sqlserver, execute_script, sqlserver_enabled, sqlserver_name


OPTIONAL = {"cdc_event", "cdc_checkpoint", "employee_warehouse", "oltp_feature_migration"}
SQL_TABLE = re.compile(r"CREATE TABLE dbo\.(\w+)\s*\((.*?)\n\s*\)", re.S | re.I)
SQL_COLUMN = re.compile(
    r"^\s*\[?(\w+)\]?\s+(BIGINT|FLOAT\(53\)|NVARCHAR\((\d+|MAX)\))(?=\s|,|$)",
    re.M | re.I,
)


def _schema(layer):
    root = Path(current_app.config["PROJECT_ROOT"]) / "sql" / "sqlserver"
    paths = [root / f"{layer}_schema.sql"]
    if layer == "oltp":
        paths.append(root / "oltp_features.sql")
    tables = {}
    for path in paths:
        for table, definition in SQL_TABLE.findall(path.read_text(encoding="utf-8")):
            tables[table] = {column: (kind, length) for column, kind, length in SQL_COLUMN.findall(definition)}
    return tables


def _source(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.execute("BEGIN")
    return db


def _inspect(db, schema):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    report = {}
    for table, definition in schema.items():
        if table not in tables and table in OPTIONAL:
            continue
        if table not in tables:
            raise ValueError(f"SQLite source table missing: {table}")
        source_columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
        unknown = set(source_columns) - definition.keys()
        missing = definition.keys() - set(source_columns)
        if unknown or missing - ({"source_order_id"} if table == "fact_sales" else set()):
            raise ValueError(f"{table}: unexpected columns {sorted(unknown)}, missing columns {sorted(missing)}")
        for column in source_columns:
            _, length = definition[column]
            if length.isdigit():
                values = db.execute(f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL')
                if any(len(str(value[0]).encode("utf-16-le")) // 2 > int(length) for value in values):
                    raise ValueError(f"{table}.{column} exceeds nvarchar({length})")
        report[table] = (source_columns, db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    return report


def _provision(names, schema):
    with closing(connect_sqlserver("master")) as master:
        existing = {}
        for layer, name in names.items():
            state = master.execute(
                "SELECT snapshot_isolation_state FROM sys.databases WHERE name = ?", (name,)
            ).fetchone()
            existing[name] = state
            if state is None:
                continue
            tables = master.execute(
                f"SELECT s.name AS schema_name, t.name AS table_name "
                f"FROM [{name}].sys.tables t JOIN [{name}].sys.schemas s ON s.schema_id = t.schema_id"
            ).fetchall()
            for row in tables:
                if row["schema_name"] != "dbo" or row["table_name"] not in schema[layer]:
                    raise ValueError(f"Target {name} has a table outside the QuocDat schema")
                table = row["table_name"]
                if master.execute(f"SELECT TOP (1) 1 FROM [{name}].dbo.[{table}]").fetchone():
                    raise ValueError(f"Target {name}.{table} already contains data")
        for name in names.values():
            state = existing[name]
            if state is None:
                master.execute(f"CREATE DATABASE [{name}] COLLATE Latin1_General_100_BIN2")
            if state is None or state[0] != 1:
                master.execute(f"ALTER DATABASE [{name}] SET ALLOW_SNAPSHOT_ISOLATION ON")
    for layer in names:
        execute_script(layer, f"{layer}_schema.sql")
    execute_script("oltp", "oltp_features.sql")
    execute_script("dwh", "ssas_source.sql")


def _copy_table(target, source, database, table, columns, schema, row_count):
    destination = f"[{database}].dbo.[{table}]"
    identities = target.execute(
        f"SELECT name FROM [{database}].sys.identity_columns WHERE object_id = OBJECT_ID(?)",
        (destination,),
    ).fetchall()
    identity = identities[0][0] if identities else None
    names = ", ".join(f"[{column}]" for column in columns)
    fields = ", ".join(
        f"[{column}] {schema[column][0]} '$[{index}]'" for index, column in enumerate(columns)
    )
    insert = f"INSERT INTO {destination} ({names}) SELECT {names} FROM OPENJSON(CONVERT(nvarchar(max), ?)) WITH ({fields})"
    if identity:
        target.execute(f"SET IDENTITY_INSERT {destination} ON")
    source_names = ", ".join(f'"{column}"' for column in columns)
    cursor = source.execute(f'SELECT {source_names} FROM "{table}"')
    while rows := cursor.fetchmany(100):
        target.execute(insert, (json.dumps(rows, ensure_ascii=False, allow_nan=False, separators=(",", ":")),))
    if identity:
        target.execute(f"SET IDENTITY_INSERT {destination} OFF")
        seq = source.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
        if seq:
            maximum = source.execute(f'SELECT MAX("{identity}") FROM "{table}"').fetchone()[0]
            if maximum is None or seq[0] > maximum:
                seed = int(seq[0]) + int(maximum is None)
                target.execute(f"EXEC [{database}].sys.sp_executesql N'DBCC CHECKIDENT (''dbo.{table}'', RESEED, {seed}) WITH NO_INFOMSGS'")
    if target.execute(f"SELECT COUNT_BIG(*) FROM {destination}").fetchone()[0] != row_count:
        raise ValueError(f"Row count mismatch in {database}.{table}")


def migrate(source_paths, *, check_only=False):
    schema = {layer: _schema(layer) for layer in DATABASE_KEYS}
    with ExitStack() as stack:
        sources = {layer: stack.enter_context(closing(_source(path))) for layer, path in source_paths.items()}
        plan = {layer: _inspect(sources[layer], definition) for layer, definition in schema.items()}
        counts = {layer: {table: details[1] for table, details in tables.items()} for layer, tables in plan.items()}
        if check_only:
            return counts
        names = {layer: sqlserver_name(layer) for layer in schema}
        if len({name.casefold() for name in names.values()}) != len(names):
            raise ValueError("Each layer requires a separate SQL Server database")
        if any(name.casefold() in {"master", "model", "msdb", "tempdb"} for name in names.values()):
            raise ValueError("Use application database names outside the SQL Server system databases")
        _provision(names, schema)
        target = stack.enter_context(closing(connect_sqlserver("master")))
        target.begin()
        with target:
            for layer, tables in schema.items():
                for table in tables:
                    if target.execute(f"SELECT TOP (1) 1 FROM [{names[layer]}].dbo.[{table}] WITH (TABLOCKX, HOLDLOCK)").fetchone():
                        raise ValueError(f"Target {names[layer]}.{table} already contains data")
            oltp = names["oltp"]
            for table in ("orders", "order_items", "invoices"):
                target.execute(f"EXEC [{oltp}].sys.sp_executesql N'DISABLE TRIGGER dbo.cdc_{table} ON dbo.{table}'")
            for layer, tables in plan.items():
                for table, (columns, count) in tables.items():
                    _copy_table(target, sources[layer], names[layer], table, columns, schema[layer][table], count)
            for table in ("orders", "order_items", "invoices"):
                target.execute(f"EXEC [{oltp}].sys.sp_executesql N'ENABLE TRIGGER dbo.cdc_{table} ON dbo.{table}'")
        return counts


@click.command("migrate-sqlserver")
@click.option("--source-dir", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--check-only", is_flag=True, help="Validate SQLite sources without connecting to SQL Server.")
def migrate_command(source_dir, check_only):
    if not check_only and not sqlserver_enabled():
        raise click.ClickException("Set QUOCDAT_SQLSERVER before importing.")
    paths = {
        layer: source_dir / f"{layer}.db" if source_dir else Path(current_app.config[key])
        for layer, key in DATABASE_KEYS.items()
    }
    try:
        report = migrate(paths, check_only=check_only)
    except (RuntimeError, ValueError, sqlite3.Error) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, indent=2))


def init_app(app):
    app.cli.add_command(migrate_command)

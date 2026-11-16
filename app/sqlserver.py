"""SQL Server connection and the small SQL dialect used by the application."""

from __future__ import annotations

import re


class DatabaseError(RuntimeError):
    pass


class Row:
    """Support the indexed, named and mapping access used by Flask and ETL."""

    def __init__(self, columns, values):
        self._columns = columns
        self._values = tuple(values)
        self._names = {name.casefold(): index for index, name in enumerate(columns)}

    def keys(self):
        return self._columns

    def __getitem__(self, index):
        return self._values[self._names[index.casefold()] if isinstance(index, str) else index]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


class Result:
    def __init__(self, rows=(), rowcount=-1, lastrowid=None):
        self.rows = iter(rows)
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return self.rows


IGNORE_KEYS = {
    "platforms": ("code",),
    "warehouses": ("warehouse_code",),
    "suppliers": ("supplier_code",),
    "users": ("email",),
    "carts": ("customer_id",),
    "products": ("natural_key",),
    "inventory": ("product_id", "warehouse_id"),
    "dim_date": ("date_key",),
    "fact_product_snapshot": ("source_record_hash", "snapshot_at"),
    "fact_procurement": ("source_procurement_item_id",),
    "employee_warehouse": ("employee_id", "warehouse_id"),
    "etl_batch": ("batch_id",),
}
IDENTITY_RESULTS = {
    "users", "carts", "orders", "procurement_receipts", "products", "categories", "dim_product",
}
INSERT = re.compile(
    r"INSERT (?:OR (IGNORE|REPLACE) )?INTO (\w+)\s*(?:\(([^)]+)\))?\s*"
    r"VALUES\s*\(([^)]*)\)(?:\s+ON CONFLICT\(([^)]+)\) DO UPDATE SET\s+(.*))?",
    re.I | re.S,
)
PAGING = re.compile(r"\s+LIMIT (\?|[0-9]+)(?: OFFSET (\?|[0-9]+))?\s*$", re.I)


def _merge(match):
    mode, table, raw_columns, binds, conflict, assignments = match.groups()
    columns = [value.strip() for value in raw_columns.split(",")] if raw_columns else list(IGNORE_KEYS[table])
    keys = [value.strip() for value in conflict.split(",")] if conflict else IGNORE_KEYS[table]
    join = " AND ".join(f"dest.[{key}] = incoming.[{key}]" for key in keys)
    names = ", ".join(f"[{column}]" for column in columns)
    values = ", ".join(f"incoming.[{column}]" for column in columns)
    update = ""
    if mode == "REPLACE":
        assignments = ", ".join(f"{column} = excluded.{column}" for column in columns if column not in keys)
    if assignments:
        assignments = re.sub(r"\bexcluded\.(\w+)", r"incoming.[\1]", assignments)
        assignments = re.sub(rf"\b{table}\.(\w+)", r"dest.[\1]", assignments)
        update = "WHEN MATCHED THEN UPDATE SET " + assignments
    return (
        f"MERGE dbo.[{table}] WITH (HOLDLOCK) AS dest "
        f"USING (VALUES ({binds})) AS incoming ({names}) ON {join} "
        f"{update} WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({values});"
    )


def translate(sql, params=()):
    sql = sql.strip().rstrip(";")
    match = INSERT.fullmatch(sql)
    identity = None
    if match:
        mode, table, _, _, conflict, _ = match.groups()
        if mode or conflict:
            sql = _merge(match)
        identity = table if table in IDENTITY_RESULTS else None
    sql = re.sub(r"\bCURRENT_TIMESTAMP\b", "CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)", sql)
    sql = re.sub(r"\bAS TEXT\)", "AS nvarchar(64))", sql, flags=re.I)
    sql = re.sub(r"\bAS INTEGER\)", "AS bigint)", sql, flags=re.I)
    sql = re.sub(r"\browid DESC\b", "run_id DESC", sql, flags=re.I)
    sql = re.sub(r"\b(changed_sales_order|current_sales_line)\b", r"#\1", sql)
    paging = PAGING.search(sql)
    if paging:
        limit, offset = paging.groups()
        sql = sql[:paging.start()]
        if offset is not None:
            sql += f" OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
            if limit == offset == "?":
                params = (*params[:-2], params[-1], params[-2])
        elif re.search(r"\bORDER BY\b", sql, flags=re.I):
            sql += f" OFFSET 0 ROWS FETCH NEXT {limit} ROWS ONLY"
        else:
            sql = re.sub(r"^SELECT\s+(DISTINCT\s+)?", lambda m: m[0] + f"TOP ({limit}) ", sql, count=1, flags=re.I)
            if limit == "?":
                params = (params[-1], *params[:-1])
    return sql, tuple(params), identity


def connect(connection_string: str):
    try:
        import pyodbc
    except ImportError as exc:
        raise DatabaseError("Install the SQL Server dependency with: pip install pyodbc") from exc
    try:
        raw = pyodbc.connect(connection_string, autocommit=True, timeout=5)
    except pyodbc.Error as exc:
        raise DatabaseError(str(exc)) from exc
    return Connection(raw, pyodbc.Error)


class Connection:
    dialect = "sqlserver"

    def __init__(self, raw, driver_error):
        self.raw = raw
        self.driver_error = driver_error
        self.in_transaction = False

    def _execute(self, statement, params=(), *, identity=False):
        cursor = self.raw.cursor()
        try:
            cursor.execute(statement, params)
            rowcount = cursor.rowcount
            if identity:
                while not cursor.description and cursor.nextset():
                    pass
                generated = cursor.fetchone() if cursor.description else None
                return Result(rowcount=rowcount, lastrowid=generated[0] if generated else None)
            rows = ()
            if cursor.description:
                columns = tuple(column[0] for column in cursor.description)
                rows = [Row(columns, row) for row in cursor.fetchall()]
            return Result(rows, rowcount)
        except self.driver_error as exc:
            raise DatabaseError(str(exc)) from exc
        finally:
            cursor.close()

    def begin(self, write=True):
        if self.in_transaction:
            raise DatabaseError("A transaction is already active")
        level = "READ COMMITTED" if write else "SNAPSHOT"
        self._execute(f"SET TRANSACTION ISOLATION LEVEL {level}; BEGIN TRANSACTION;")
        self.in_transaction = True
        if write:
            try:
                self._execute(
                    "DECLARE @result int; EXEC @result = sys.sp_getapplock "
                    "@Resource = 'QuocDat.application-writes', @LockMode = 'Exclusive', "
                    "@LockOwner = 'Transaction', @LockTimeout = 30000; "
                    "IF @result < 0 THROW 51000, 'Unable to obtain the QuocDat write lock.', 1;"
                )
            except DatabaseError:
                self.rollback()
                raise

    def execute(self, sql, params=()):
        operation = sql.strip().upper()
        if operation in {"BEGIN", "BEGIN IMMEDIATE"}:
            self.begin(write=operation == "BEGIN IMMEDIATE")
            return Result()
        if operation.startswith("CREATE TEMP TABLE IF NOT EXISTS"):
            name = operation.split()[6].lower()
            if name not in {"changed_sales_order", "current_sales_line"}:
                raise DatabaseError(f"Unknown temporary table {name}")
            return self._execute(f"IF OBJECT_ID('tempdb..#{name}') IS NULL CREATE TABLE #{name} (id bigint PRIMARY KEY)")
        if operation.startswith("PRAGMA TABLE_INFO"):
            table = re.fullmatch(r"PRAGMA TABLE_INFO\((\w+)\)", operation)[1].lower()
            return self._execute("SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?)", (f"dbo.{table}",))
        if operation == "DELETE FROM SQLITE_SEQUENCE":
            return Result()
        sql, params, identity = translate(sql, params)
        if re.match(r"^(INSERT|UPDATE|DELETE|MERGE)\b", sql, re.I) and not self.in_transaction:
            self.begin()
        if identity:
            sql = sql.rstrip(";") + "; SELECT CAST(SCOPE_IDENTITY() AS bigint) AS generated_id;"
        return self._execute(sql, params, identity=bool(identity))

    def executemany(self, sql, parameters):
        match = INSERT.fullmatch(sql.strip().rstrip(";"))
        if match and not match[1] and not match[5]:
            rows = [tuple(params) for params in parameters]
            if not rows:
                return Result(rowcount=0)
            statement, _, _ = translate(sql)
            if not self.in_transaction:
                self.begin()
            cursor = self.raw.cursor()
            try:
                cursor.executemany(statement, rows)
                return Result(rowcount=len(rows))
            except self.driver_error as exc:
                raise DatabaseError(str(exc)) from exc
            finally:
                cursor.close()
        count = 0
        for params in parameters:
            result = self.execute(sql, params)
            count += max(result.rowcount, 0)
        return Result(rowcount=count)

    def executescript(self, sql):
        for batch in re.split(r"^\s*GO\s*$", sql, flags=re.I | re.M):
            if batch.strip():
                self._execute(batch)

    def commit(self):
        if self.in_transaction:
            self._execute("IF @@TRANCOUNT > 0 COMMIT TRANSACTION")
            self.in_transaction = False

    def rollback(self):
        if self.in_transaction:
            self._execute("IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION")
            self.in_transaction = False

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self.rollback() if exc_type else self.commit()

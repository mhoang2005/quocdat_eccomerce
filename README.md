# QuocDat Marketplace — E-commerce & Data Warehouse System

QuocDat Marketplace is a complete course project that connects a transactional web application to a Kimball Data Warehouse and OLAP layer. It includes three isolated user roles, Lazada/Tiki raw data, OLTP, Staging/DQ, ETL, a star schema with SCD Type 2, Materialized Views, and a precomputed Sales Cube.

## Completed scope

- Responsive web application for customers, procurement staff, and administrators.
- OLTP operations: accounts, catalog, cart, checkout, payment, invoices, inventory, procurement, and audit logs.
- Raw layer: the original files remain unchanged under `data/raw/lazada` and `data/raw/tiki`.
- Staging layer: schema standardization, duplicate flags, data-quality checks, lineage, and OLTP staging.
- Full and incremental ETL modes.
- Kimball DWH with 6 dimensions, 4 facts, and an SCD Type 2 `Dim_Product`.
- Four complete-refresh Materialized Views for sales, procurement, inventory, and marketplace snapshots.
- Course-aligned four-dimensional Sales Cube: Time, Product, Location, and Store/Seller (individual customers are preserved in Fact_Sales and as a cube metric `customer_count` to prevent high-cardinality cube explosion).
- Product uses category, Location uses customer city, and marketplace Platform is the available Store/Seller channel.
- Five time hierarchy levels and all 8 grouping sets for the three non-time dimensions.
- Explicit Roll-up, Drill-down, Slice, Dice, and Pivot controls in the Cube Explorer.
- Admin center for lineage, DQ results, warehouse row counts, and ETL run history.
- OLAP administration page with refresh lineage and a filterable Cube Explorer.
- Filterable DWH Analytics Dashboard with KPIs, commercial trends, category demand, platform benchmarks, and warehouse health.
- Three-Fact Drill-across across Sales, Procurement, and Inventory at the conformed `Date × Product Category × Warehouse` grain.
- Automated tests for the primary business workflows.

The catalog preserves source-native product names and categories because those values belong to the raw marketplace datasets. All application controls, system messages, seeded reference data, and project documentation are in English.

## Quick start on Windows

Double-click [start_demo.bat](./start_demo.bat) to connect to SQL Server `.\SQL` and open `http://127.0.0.1:5000`. See the [SQL Server and Visual Studio guide](./docs/SQL_SERVER.md) for moving to another instance, opening the SSAS cube, and running the SQL Server benchmark.

## Demo accounts

| Role | Email | Password | Main workspace |
|---|---|---|---|
| Customer | `customer@quocdat.local` | `Customer@123` | Shopping, checkout, invoices |
| Staff | `employee@quocdat.local` | `Staff@123` | Goods receipts and inventory |
| Admin | `admin@quocdat.local` | `Admin@123` | Administration, SCD2, ETL, OLAP, Analytics |

## Useful commands

```powershell
# Incremental ETL
.\.venv\Scripts\python.exe -m flask --app run:app run-etl --mode incremental

# Full DWH reload
.\.venv\Scripts\python.exe -m flask --app run:app run-etl --mode full

# Refresh only the Materialized Views and Sales Cube
.\.venv\Scripts\python.exe -m flask --app run:app refresh-olap

# Automated tests
.\.venv\Scripts\python.exe -m pytest -q

# Check the three database connections
.\.venv\Scripts\python.exe -m flask --app run:app db-status
```

## Project structure

```text
app/                    Flask routes, business logic, and ETL
data/raw/lazada/        Original Lazada source
data/raw/tiki/          Original Tiki source
docs/                   Architecture and live demo guide
instance/               Archived SQLite source databases and generated XMLA
sql/sqlserver/          SQL Server schema, source views, and benchmark
ssas/                   Sales Cube generation and MDX verification
static/ + templates/    Responsive user interface
tests/                  End-to-end application tests
```

## Database optimization and access controls

- **Marketplace partitions and index.** SQL Server partitions `fact_product_snapshot` by month using `date_key`. The covering index uses `platform_key` and `date_key` and includes `sale_price`.
- **Sales change data capture.** OLTP triggers capture order, order-line, and invoice changes in the source transaction. The first ETL builds the sales baseline. Later incremental runs stage only the affected orders and reconcile cancelled, refunded, or deleted sales lines. Admin → ETL shows the checkpoint and the counts for each run. Procurement, inventory, catalog staging, and OLAP refresh retain their existing schedules.
- **Warehouse access and contact masking.** Admin → Settings → Staff warehouse access grants or revokes assignments. SQL Server enforces row-level rules on orders, stock, and receipts using the app's session context. SQL Server masks user email and phone for principals without `UNMASK`.

### Archived SQLite benchmark

```powershell
.\.venv\Scripts\python.exe -m benchmarks.snapshot_query --runs 250
```

The script opens the DWH read-only, measures on an in-memory copy, verifies result equality, and prints each query plan. Sample median timings on 17,582 snapshots with a warmed cache are:

| Query | Matched rows | Existing index | Covering index | Monthly table + covering index |
|---|---:|---:|---:|---:|
| Tiki, Jan 2026 | 1,200 | 0.5703 ms | 0.2256 ms | 0.2126 ms |
| Lazada, Feb 2026 | 15,805 | 12.4762 ms | 3.0844 ms | 2.9552 ms |

The benchmark measures a count and average by platform and month. The covering index provides most of the gain for these queries. The monthly projection adds storage and refresh work, and these timings exclude both that work and the rest of the dashboard.

Continue with the [system architecture](./docs/ARCHITECTURE.md) and [live demo script](./docs/DEMO_SCRIPT.md).

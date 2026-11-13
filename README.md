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
- Course-aligned five-dimensional Sales Cube: Time, Product, Customer, Location, and Store/Seller.
- Product uses category, Location uses customer city, and marketplace Platform is the available Store/Seller channel.
- Five time hierarchy levels and all 16 grouping sets for the four non-time dimensions.
- Explicit Roll-up, Drill-down, Slice, Dice, and Pivot controls in the Cube Explorer.
- Admin center for lineage, DQ results, warehouse row counts, and ETL run history.
- OLAP administration page with refresh lineage and a filterable Cube Explorer.
- Filterable DWH Analytics Dashboard with KPIs, commercial trends, category demand, platform benchmarks, and warehouse health.
- Three-Fact Drill-across across Sales, Procurement, and Inventory at the conformed `Date × Product Category × Warehouse` grain.
- Automated tests for the primary business workflows.

The catalog preserves source-native product names and categories because those values belong to the raw marketplace datasets. All application controls, system messages, seeded reference data, and project documentation are in English.

## Quick start on Windows

The fastest option is to double-click [start_demo.bat](./start_demo.bat). It creates the Python environment when needed, installs dependencies, initializes missing databases, and opens `http://127.0.0.1:5000`.

Manual PowerShell setup:

```powershell
cd "C:\Users\PC FUJISU\OneDrive\giaotrinh\Kho dữ liệu\tiểu luận môn học"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app run:app init-system
.\.venv\Scripts\python.exe run.py
```

The first initialization takes a few seconds because it stages 17,640 raw snapshots. Later starts only require `python run.py`, and existing transactions remain available.

To recreate all three databases:

```powershell
.\.venv\Scripts\python.exe -m flask --app run:app init-system --reset
```

This command only recreates database files under `instance`; it never deletes the raw source files.

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

# Display the three database paths
.\.venv\Scripts\python.exe -m flask --app run:app db-status
```

## Project structure

```text
app/                    Flask routes, business logic, and ETL
data/raw/lazada/        Original Lazada source
data/raw/tiki/          Original Tiki source
docs/                   Architecture and live demo guide
instance/               oltp.db, staging.db, dwh.db
sql/                    DDL for all three data layers
static/ + templates/    Responsive user interface
tests/                  End-to-end application tests
```

Continue with the [system architecture](./docs/ARCHITECTURE.md) and [live demo script](./docs/DEMO_SCRIPT.md).

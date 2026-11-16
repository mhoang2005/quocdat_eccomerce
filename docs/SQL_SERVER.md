# Run QuocDat on SQL Server and SSAS

## Connections on this workstation

| Component | Server | Database |
| --- | --- | --- |
| SQL Server Database Engine | `.\SQL` | `QuocDatOLTP`, `QuocDatStaging`, `QuocDatDWH` |
| SQL Server Analysis Services, Multidimensional | `localhost` | `QuocDatSales` |

Use Windows Authentication. Launch the web app with [start_demo.bat](../start_demo.bat) or `.\.venv\Scripts\python.exe run.py`. The app connects to the three Database Engine databases. The web Cube Explorer reads the SQL Server `cube_sales` table produced with T-SQL `CUBE`. Visual Studio and MDX use the SSAS Sales cube.

## Move the data to another instance

Prepare the Python environment from the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On a fresh clone, create the three demo SQLite files from the bundled raw data before running the migration. Skip this step when you already have SQLite data to migrate.

```powershell
$env:QUOCDAT_DB_BACKEND = 'sqlite'
.\.venv\Scripts\python.exe -m flask --app run:app init-system
Remove-Item Env:QUOCDAT_DB_BACKEND
```

Stop the application during the one-time import to get a consistent snapshot across the SQLite files. The migration opens the source files read-only, copies primary keys and identity sequences, validates the target row count for every copied table, and refuses populated targets. SQL Server's partitioned fact contains all rows from the source fact. The SQLite monthly projection tables can be regenerated from the original files.

```powershell
.\.venv\Scripts\python.exe -m flask --app run:app migrate-sqlserver --check-only
.\.venv\Scripts\python.exe -m flask --app run:app migrate-sqlserver
.\.venv\Scripts\python.exe -m flask --app run:app db-status
```

Set `QUOCDAT_SQLSERVER` to a custom ODBC connection string without a database name to override the local `.\SQL` default. Set `QUOCDAT_SQLSERVER_OLTP`, `QUOCDAT_SQLSERVER_STAGING`, or `QUOCDAT_SQLSERVER_DWH` to override database names. The default trusts the certificate of the local demo server. For the archived SQLite mode, set `QUOCDAT_DB_BACKEND=sqlite`.

## Open the Sales cube in Visual Studio

1. In Visual Studio with Microsoft Analysis Services Projects installed, choose **Create a new project → Import from Server (Multidimensional and Data Mining)**.
2. Enter **`localhost`** as the Analysis Services server and choose **`QuocDatSales`**. Open **Cubes → Sales.cube → Browser**.
3. The cube exposes Calendar, Product Category, Customer City, and Platform. It includes additive sales measures, distinct order and customer counts, and average selling price. The [MDX check](../ssas/Verify-Sales.mdx) returns the grand total.
4. After running the app's ETL, use **Process Full** in SSMS or Visual Studio to refresh the SSAS copy from `QuocDatDWH`.

To deploy the model on a fresh instance, run the SQL grants as an administrator. Edit the principal in the grant script if the SSAS service uses a different Windows account. Use the Multidimensional instance for `-AnalysisServer` and the Database Engine for `-SqlServer`.

```powershell
sqlcmd -S '.\SQL' -E -C -d QuocDatDWH -b -i '.\ssas\grant_sales_source.sql'
.\ssas\New-SalesCube.ps1 -SqlServer '.\SQL' -AnalysisServer 'localhost' -Provider 'MSOLEDBSQL19' -TrustServerCertificate
```

The generator also writes `instance/quocdat-sales.xmla`. Supply `-AmoAssembly` if it cannot find the AMO library installed with Visual Studio. When `-AnalysisServer` is omitted, the generator only writes the XMLA.

## Test the database features

- In SSMS, connect to `.\SQL` as **Database Engine**, select `QuocDatDWH`, turn on **Include Actual Execution Plan**, and run [benchmark_snapshot.sql](../sql/sqlserver/benchmark_snapshot.sql). Compare the returned counts and average price, logical reads in **Messages**, and partition information in the final execution plan.
- In the app, **Admin → ETL** displays sales CDC. A single order operation can create events for the order, lines, and invoice. The SQL Server triggers write to `QuocDatOLTP.dbo.cdc_event` in the same write transaction.
- The SQL Server security policies filter orders and warehouse rows using the authenticated Flask user's session context. Separate SQL logins need their own database permissions. Database masking applies to SQL principals without `UNMASK`. The app also masks other users’ contacts in Admin → Users.

The SQL Server benchmark measured 1,200 matches out of 17,582 snapshots for Tiki in January 2026. All three queries returned an average sale price of 741,858.33.

| Configuration | Logical reads |
| --- | ---: |
| Unpartitioned, date/product index | 1,786 |
| Unpartitioned, covering index | 9 |
| Monthly partition and covering index | 11 |

The read count measures this single filtered query. The covering index accounted for most of the improvement.

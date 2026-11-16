# Live Product Demo Script

Suggested duration: 12–14 minutes. No slides are required.

## 1. Introduce the system — 1 minute

Run `start_demo.bat`, open the home page, and summarize the pipeline: `Web/OLTP → Staging/DQ → Kimball DWH → Materialized Views / Sales Cube → Analytics Dashboard → Drill-across`.

## 2. Customer flow — 2 minutes

1. Sign in with `customer@quocdat.local / Customer@123`.
2. Search or filter the catalog, open a product, and add it to the cart.
3. Complete checkout with the demo card.
4. Open the newly created invoice.
5. Explain that one transaction creates the order, lines, payment, and invoice while decrementing inventory; any error rolls everything back.

## 3. Procurement staff flow — 2 minutes

1. Sign out and use `employee@quocdat.local / Staff@123`.
2. Open “Create Goods Receipt.”
3. Select a supplier and receiving warehouse.
4. Type `Tiki` or part of a product name/code, select a suggestion, and enter quantity and unit cost.
5. Confirm the receipt and open the resulting document.
6. Explain that inventory increases immediately and weighted-average cost is recalculated.

## 4. Admin and SCD2 flow — 2 minutes

1. Sign in with `admin@quocdat.local / Admin@123`.
2. Open Product Catalog and edit a product name or brand.
3. Open “ETL & Data Warehouse,” select `Incremental`, and click “Run ETL.”
4. Point out the pipeline, row counts for 6 dimensions and 4 facts, DQ summary, and ETL history.
5. Explain that the previous Dim_Product row closes while the new row receives a new surrogate key and `is_current = 1`.
6. Explain that a successful ETL automatically refreshes the OLAP layer and records its lineage.

## 5. Materialized Views and Sales Cube — 2 minutes

1. Open “OLAP Cube & MVs.”
2. Show the four physical Materialized Views and state the grain of each one.
3. Explain why SQLite uses indexed physical aggregate tables instead of native Materialized Views.
4. In Cube Explorer, use Roll-up from `DAY` to `YEAR`, then Drill-down to `QUARTER`.
5. Slice Store/Seller to one platform, dice Product and Location, and click “Apply Slice / Dice.”
6. Point out the analytical dimensions: Time, Product, Location, and Store/Seller. Explain that Category represents Product, Customer City represents Location, Platform is the available Store/Seller channel, and Customer is intentionally kept as an aggregate metric (`customer_count`) to avoid high-cardinality cube explosion.
7. Switch Pivot View from “Product × Time” to “Location × Time.”
8. Explain that each time level has all 8 detailed/`ALL` grouping sets and that the grand total reconciles with `Fact_Sales`.

## 6. Analytics Dashboard and Drill-across — 2 minutes

1. Open “Analytics Dashboard.”
2. Filter by Year, Product Category, Platform, or Warehouse and point out which business processes each filter can validly affect.
3. Show the DWH KPIs, commercial trend, marketplace category demand, platform benchmark, and latest warehouse health.
4. Scroll to “Sales × Procurement × Inventory.”
5. Explain that each Fact is aggregated independently before measures are aligned at `Date × Product Category × Warehouse`.
6. Point out the conformed-grain columns and the Sales, Procurement, and Inventory measure groups in one row.
7. State that direct Fact-to-Fact joins are avoided because they would multiply rows. Platform is excluded because Procurement has no Platform key; Marketplace Snapshot is separate because it has no Warehouse key.

## 7. Close with the model — 1 minute

Open the bus matrix in `docs/ARCHITECTURE.md` and explain:

- Fact_Sales grain: one product line in one paid order.
- Fact_Procurement grain: one product line in one goods receipt.
- Fact_Inventory grain: product × warehouse × date.
- Fact_Product_Snapshot grain: product × platform × crawl timestamp.
- Materialized Views accelerate repeated summaries without scanning facts.
- The Sales Cube demonstrates Roll-up, Drill-down, Slice, Dice, and Pivot.
- The Dashboard turns DWH measures into decision views.
- Drill-across combines measures from three Facts only after aligning their conformed grain.

## Reset the demo when needed

```powershell
.\.venv\Scripts\python.exe -m flask --app run:app init-system --reset
```

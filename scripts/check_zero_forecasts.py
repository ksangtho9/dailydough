"""
Diagnostic script: classify zero forecast days as legitimate vs bugs.

A zero forecast is "legitimate" when the product's underlying sales data is
itself mostly zero (sparse/low-volume product). It is a "bug" when the sales
data looks healthy but the forecast is still producing zeros.

Usage:
    py scripts/check_zero_forecasts.py
    py scripts/check_zero_forecasts.py --db path/to/bakezy.db
    py scripts/check_zero_forecasts.py --threshold 0.5
"""
import argparse
import sqlite3
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Classify zero forecast days.")
    parser.add_argument("--db", default="bakezy.db", help="Path to SQLite DB")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.60,
        help="Sales zero-rate above which zeros are considered legitimate (default: 0.60)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        # Try relative to script location
        db_path = Path(__file__).parent.parent / args.db
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # --- Forecast zeros ---
    cur.execute("""
        SELECT
            df.product_id,
            p.name AS product_name,
            b.name AS bakery_name,
            COUNT(*) AS total_forecast_days,
            SUM(CASE WHEN df.yhat = 0 THEN 1 ELSE 0 END) AS zero_forecast_days,
            ROUND(AVG(df.yhat), 3) AS avg_yhat,
            ROUND(MIN(df.yhat), 3) AS min_yhat,
            ROUND(MAX(df.yhat), 3) AS max_yhat
        FROM daily_forecasts df
        JOIN products p ON p.id = df.product_id
        JOIN bakeries b ON b.id = p.bakery_id
        GROUP BY df.product_id
        HAVING zero_forecast_days > 0
        ORDER BY zero_forecast_days DESC
    """)
    forecast_rows = cur.fetchall()

    if not forecast_rows:
        print("No products with zero forecast days found. All clear!")
        conn.close()
        return

    product_ids = [r[0] for r in forecast_rows]

    # --- Sales zero-rate for those products ---
    placeholders = ",".join("?" * len(product_ids))
    cur.execute(f"""
        SELECT
            product_id,
            COUNT(*) AS total_days,
            SUM(CASE WHEN quantity_sold = 0 THEN 1 ELSE 0 END) AS zero_sales_days,
            ROUND(AVG(quantity_sold), 3) AS avg_sales,
            ROUND(MAX(quantity_sold), 3) AS max_sales
        FROM sales_records
        WHERE product_id IN ({placeholders})
        GROUP BY product_id
    """, product_ids)
    sales_map = {r[0]: r for r in cur.fetchall()}

    # --- Model info ---
    cur.execute(f"""
        SELECT product_id, selected_model_type, MAX(created_at) AS latest_run
        FROM model_runs
        WHERE product_id IN ({placeholders})
        GROUP BY product_id
    """, product_ids)
    model_map = {r[0]: r for r in cur.fetchall()}

    conn.close()

    # --- Classify and print ---
    bugs = []
    legitimate = []

    print(f"\n{'='*100}")
    print(f"  ZERO FORECAST ANALYSIS  (legitimacy threshold: sales zero-rate > {args.threshold:.0%})")
    print(f"{'='*100}")
    print(f"{'ID':>5}  {'Product':<35}  {'Bakery':<12}  {'Model':<14}  "
          f"{'0-fcst':>6}  {'Sales0%':>7}  {'AvgSales':>8}  {'Classification'}")
    print("-" * 100)

    for row in forecast_rows:
        pid, name, bakery, total_fcst, zero_fcst, avg_yhat, min_yhat, max_yhat = row
        sales = sales_map.get(pid)
        model_info = model_map.get(pid)
        model_type = model_info[1] if model_info else "unknown"

        if sales:
            total_s, zero_s, avg_s, max_s = sales[1], sales[2], sales[3], sales[4]
            sales_zero_rate = zero_s / total_s if total_s > 0 else 0.0
        else:
            sales_zero_rate = 0.0
            avg_s = 0.0

        is_legitimate = sales_zero_rate >= args.threshold
        classification = "LEGITIMATE (sparse data)" if is_legitimate else "BUG (sales ok, forecast zero)"

        print(f"{pid:>5}  {name[:35]:<35}  {bakery[:12]:<12}  {model_type:<14}  "
              f"{zero_fcst:>6}  {sales_zero_rate:>6.0%}  {avg_s:>8.2f}  {classification}")

        if is_legitimate:
            legitimate.append(pid)
        else:
            bugs.append(pid)

    print(f"\n{'='*100}")
    print(f"  SUMMARY")
    print(f"{'='*100}")
    print(f"  Total products with 1+ zero forecast day : {len(forecast_rows)}")
    print(f"  Legitimate (sparse sales data)           : {len(legitimate)}")
    print(f"  Bugs (sales fine, forecasts wrong)       : {len(bugs)}")
    if bugs:
        print(f"\n  Bug product IDs: {sorted(bugs)}")
        print(f"\n  ACTION REQUIRED: Retrain these products and check logs for PROPHET_FALLBACK entries.")
    else:
        print(f"\n  No bug-zeros found. Remaining zeros are data-driven (low-volume products).")


if __name__ == "__main__":
    main()

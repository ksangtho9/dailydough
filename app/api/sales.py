from datetime import datetime
import csv
from io import StringIO
from typing import List, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.bakery import DailySales, Product


router = APIRouter()


def parse_csv(content: str) -> Tuple[List[dict], List[str]]:
	reader = csv.DictReader(StringIO(content))
	required_fields = {"product_id", "sale_date", "units_sold", "revenue"}
	rows = []
	errors = []

	# Validate headers
	missing = required_fields - set((reader.fieldnames or []))
	if missing:
		errors.append(f"Missing required columns: {', '.join(sorted(missing))}")
		return [], errors

	for idx, raw in enumerate(reader, start=2):  # start=2 accounts for header being line 1
		try:
			product_id = int(raw["product_id"])
			# Expect ISO date (YYYY-MM-DD)
			sale_date = datetime.strptime(raw["sale_date"], "%Y-%m-%d").date()
			units_sold = int(raw["units_sold"])
			revenue = float(raw["revenue"])
			rows.append(
				{
					"product_id": product_id,
					"sale_date": sale_date,
					"units_sold": units_sold,
					"revenue": revenue,
				}
			)
		except Exception as exc:
			errors.append(f"Line {idx}: {exc}")
	return rows, errors


@router.post("/upload-sales", status_code=status.HTTP_201_CREATED)
async def upload_sales(file: UploadFile = File(...), db: Session = Depends(get_db)):
	if not file.filename.endswith(".csv"):
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .csv files are accepted")

	content_bytes = await file.read()
	try:
		content = content_bytes.decode("utf-8")
	except UnicodeDecodeError:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV must be UTF-8 encoded")

	rows, parse_errors = parse_csv(content)
	if not rows and parse_errors:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(parse_errors))

	inserted = 0
	skipped_missing_product = 0
	row_errors: List[str] = []

	for idx, row in enumerate(rows, start=2):
		product = db.query(Product).filter(Product.id == row["product_id"]).first()
		if not product:
			skipped_missing_product += 1
			row_errors.append(f"Line {idx}: product_id {row['product_id']} not found")
			continue
		try:
			record = DailySales(
				product_id=row["product_id"],
				sale_date=row["sale_date"],
				units_sold=row["units_sold"],
				revenue=row["revenue"],
			)
			db.add(record)
			inserted += 1
		except Exception as exc:
			row_errors.append(f"Line {idx}: {exc}")
			db.rollback()

	try:
		db.commit()
	except Exception as exc:
		db.rollback()
		raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

	return {
		"filename": file.filename,
		"inserted": inserted,
		"skipped_missing_product": skipped_missing_product,
		"parse_errors": parse_errors,
		"row_errors": row_errors,
	}



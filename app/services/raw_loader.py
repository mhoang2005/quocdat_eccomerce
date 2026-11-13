from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Iterable

from flask import current_app

from app.db import get_db


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _normal_text(value) -> str:
    text = unicodedata.normalize("NFKC", _text(value)).lower()
    return re.sub(r"\s+", " ", text)


def _money(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.-]", "", str(value))
    return float(cleaned) if cleaned else None


def _number(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[0-9]+(?:[.,][0-9]+)?", str(value))
    return float(match.group(0).replace(",", ".")) if match else None


def _sold_quantity(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    raw = str(value).lower().replace(",", ".")
    parsed = _number(raw)
    if parsed is None:
        return None
    if "k" in raw:
        parsed *= 1_000
    elif "m" in raw:
        parsed *= 1_000_000
    return int(round(parsed))


def _snapshot_at(day_value, time_value) -> str:
    day = _text(day_value)
    time = _text(time_value) or "00:00:00"
    for pattern in ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(f"{day} {time}", pattern).isoformat(timespec="seconds")
        except ValueError:
            continue
    return datetime.utcnow().isoformat(timespec="seconds")


def _canonical_hash(payload: dict, snapshot_at: str, source: str) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{source}|{snapshot_at}|{canonical}".encode("utf-8")).hexdigest()


def _lazada_natural_key(row: dict) -> str:
    identity = "|".join(
        [
            "lazada",
            _normal_text(row.get("name")),
            _normal_text(row.get("category")),
            _normal_text(row.get("origin")),
        ]
    )
    return "LAZ:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _iter_lazada(path: Path) -> Iterable[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    for index, row in enumerate(rows, start=1):
        snapshot = _snapshot_at(row.get("crawl-day"), row.get("crawl-timestamp"))
        yield {
            "source_system": "Lazada",
            "source_file": path.name,
            "source_row_number": index,
            "natural_key": _lazada_natural_key(row),
            "platform_product_id": None,
            "sku": None,
            "snapshot_at": snapshot,
            "product_name": _text(row.get("name")),
            "category_name": _text(row.get("category")) or "Uncategorized",
            "category_l1": _text(row.get("category")),
            "category_l2": None,
            "category_l3": None,
            "brand_name": None,
            "seller_id": None,
            "seller_type": None,
            "origin": _text(row.get("origin")),
            "list_price": None,
            "sale_price": _money(row.get("price")),
            "discount_amount": None,
            "discount_rate": _number(row.get("discount")),
            "quantity_sold": _sold_quantity(row.get("sold")),
            "rating": None,
            "review_count": None,
            "image_url": None,
            "raw": row,
        }


def _iter_tiki(path: Path) -> Iterable[dict]:
    blocks = json.loads(path.read_text(encoding="utf-8"))
    source_row = 0
    for block in blocks:
        if not isinstance(block.get("data"), list):
            continue
        for product in block["data"]:
            source_row += 1
            amplitude = ((product.get("visible_impression_info") or {}).get("amplitude") or {})
            product_id = product.get("id") or product.get("seller_product_id")
            snapshot = _snapshot_at(block.get("crawl-day"), block.get("crawl-timestamp"))
            quantity_sold = product.get("quantity_sold") or {}
            yield {
                "source_system": "Tiki",
                "source_file": path.name,
                "source_row_number": source_row,
                "natural_key": f"TIKI:{product_id}",
                "platform_product_id": _text(product_id),
                "sku": _text(product.get("sku")),
                "snapshot_at": snapshot,
                "product_name": _text(product.get("name")),
                "category_name": _text(block.get("category") or amplitude.get("primary_category_name"))
                or "Uncategorized",
                "category_l1": _text(amplitude.get("category_l1_name")),
                "category_l2": _text(amplitude.get("category_l2_name")),
                "category_l3": _text(amplitude.get("category_l3_name")),
                "brand_name": _text(product.get("brand_name")),
                "seller_id": _text(product.get("seller_id") or amplitude.get("seller_id")),
                "seller_type": _text(amplitude.get("seller_type")),
                "origin": None,
                "list_price": _money(product.get("list_price") or product.get("original_price")),
                "sale_price": _money(product.get("price")),
                "discount_amount": _money(product.get("discount")),
                "discount_rate": _number(product.get("discount_rate")),
                "quantity_sold": _sold_quantity(
                    quantity_sold.get("value") or amplitude.get("all_time_quantity_sold")
                ),
                "rating": _number(product.get("rating_average")),
                "review_count": int(product.get("review_count") or 0),
                "image_url": _text(product.get("thumbnail_url")),
                "raw": {"block_metadata": {k: v for k, v in block.items() if k != "data"}, "product": product},
            }


def iter_raw_products() -> Iterable[dict]:
    raw_root = Path(current_app.config["DATA_DIR"]) / "raw"
    lazada_path = raw_root / "lazada" / "lazada_raw.json"
    tiki_path = raw_root / "tiki" / "tiki_raw.json"
    if not lazada_path.exists() or not tiki_path.exists():
        raise FileNotFoundError("Expected raw files in data/raw/lazada and data/raw/tiki")
    yield from _iter_lazada(lazada_path)
    yield from _iter_tiki(tiki_path)


def _quality(row: dict) -> tuple[str, str | None]:
    issues = []
    status = "VALID"
    if not row["product_name"]:
        return "INVALID", "Missing product name"
    if row["sale_price"] is None or row["sale_price"] < 0:
        return "INVALID", "Invalid sale price"
    if row["discount_rate"] is not None and not 0 <= row["discount_rate"] <= 100:
        issues.append("Discount rate is outside the 0-100 range")
    if not row["category_name"]:
        issues.append("Missing category")
    if issues:
        status = "WARNING"
    return status, "; ".join(issues) or None


def stage_raw_products(batch_id: str, replace: bool = False) -> dict:
    connection = get_db("staging")
    if replace:
        connection.execute("DELETE FROM stg_product_snapshot WHERE source_system IN ('Lazada', 'Tiki')")

    seen_hashes: set[str] = set()
    rows_to_insert = []
    counters = {"source": 0, "valid": 0, "warning": 0, "invalid": 0, "duplicate": 0}
    for row in iter_raw_products():
        counters["source"] += 1
        status, message = _quality(row)
        counters[status.lower()] += 1
        record_hash = _canonical_hash(row["raw"], row["snapshot_at"], row["source_system"])
        duplicate = 1 if record_hash in seen_hashes else 0
        if duplicate:
            counters["duplicate"] += 1
        seen_hashes.add(record_hash)
        rows_to_insert.append(
            (
                batch_id,
                row["source_system"],
                row["source_file"],
                row["source_row_number"],
                row["natural_key"],
                row["platform_product_id"],
                row["sku"],
                row["snapshot_at"],
                row["product_name"],
                row["category_name"],
                row["category_l1"],
                row["category_l2"],
                row["category_l3"],
                row["brand_name"],
                row["seller_id"],
                row["seller_type"],
                row["origin"],
                row["list_price"],
                row["sale_price"],
                row["discount_amount"],
                row["discount_rate"],
                row["quantity_sold"],
                row["rating"],
                row["review_count"],
                row["image_url"],
                duplicate,
                status,
                message,
                record_hash,
                json.dumps(row["raw"], ensure_ascii=False, separators=(",", ":")),
            )
        )

    connection.executemany(
        """
        INSERT INTO stg_product_snapshot (
            batch_id, source_system, source_file, source_row_number, natural_key,
            platform_product_id, sku, snapshot_at, product_name, category_name,
            category_l1, category_l2, category_l3, brand_name, seller_id,
            seller_type, origin, list_price, sale_price, discount_amount,
            discount_rate, quantity_sold, rating, review_count, image_url,
            is_duplicate, dq_status, dq_message, record_hash, raw_payload
        ) VALUES ({})
        """.format(",".join("?" for _ in range(30))),
        rows_to_insert,
    )
    connection.commit()
    return counters


def product_code(natural_key: str, platform_product_id: str | None) -> str:
    if natural_key.startswith("TIKI:") and platform_product_id:
        return f"TIK-{platform_product_id}"
    return "LAZ-" + natural_key.split(":", 1)[-1][:12].upper()


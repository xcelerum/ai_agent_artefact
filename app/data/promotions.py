"""Atomic snapshot promotion ingestion; descriptions never establish validity."""

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re

from app.domain.catalog import Catalog


class PromotionDataError(ValueError):
    """Sanitized promotion source/configuration error."""


@dataclass(frozen=True)
class Promotion:
    promotion_id: int
    product_id: int
    discount_percent: Decimal
    description: str
    is_active: bool


@dataclass(frozen=True)
class PromotionBook:
    records: tuple[Promotion, ...]

    def active_for(self, product_id: int) -> Promotion | None:
        return next((p for p in self.records if p.product_id == product_id and p.is_active), None)


def _identifier(raw: str) -> int:
    if len(raw) > 20 or re.fullmatch(r'[0-9]+', raw) is None or int(raw) <= 0:
        raise ValueError
    return int(raw)


def _percentage(raw: str) -> Decimal:
    if len(raw) > 20 or re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', raw) is None:
        raise ValueError
    value = Decimal(raw)
    if not value.is_finite() or not Decimal('0') < value <= Decimal('100'):
        raise ValueError
    return value


def load_promotions(path: Path, catalog: Catalog) -> PromotionBook:
    fields = {'promotion_id', 'product_id', 'discount_percent', 'description', 'is_active'}
    known_products = {p.product_id for p in catalog.products}
    records, seen_ids, active_products = [], set(), set()
    try:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream, strict=True)
            if not reader.fieldnames or len(reader.fieldnames) != len(fields) or set(reader.fieldnames) != fields:
                raise PromotionDataError('promotions: invalid columns')
            for row in reader:
                try:
                    if None in row or None in row.values():
                        raise ValueError
                    identifier = _identifier(row['promotion_id'])
                    product_id = _identifier(row['product_id'])
                    percent = _percentage(row['discount_percent'])
                    if row['is_active'] not in ('0', '1'):
                        raise ValueError
                    active = row['is_active'] == '1'
                    if identifier in seen_ids or product_id not in known_products:
                        raise ValueError
                    if active and product_id in active_products:
                        raise ValueError
                    seen_ids.add(identifier)
                    if active:
                        active_products.add(product_id)
                    records.append(Promotion(identifier, product_id, percent, row['description'], active))
                except (ValueError, ArithmeticError):
                    raise PromotionDataError(f'promotions: row {reader.line_num}: invalid or conflicting record') from None
    except (OSError, UnicodeError, csv.Error):
        raise PromotionDataError('promotions: cannot read valid UTF-8 CSV') from None
    return PromotionBook(tuple(records))

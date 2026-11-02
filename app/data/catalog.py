"""Strict all-or-nothing CSV ingestion. Paths must be supplied explicitly.

Only product/category files are read. Diagnostics identify table, row and field,
never raw cell contents or private paths. No supplied text is executed.
"""

from collections.abc import Callable, Iterator
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from types import MappingProxyType

from app.domain.catalog import Catalog, Category, Product, ProductStatus, _normalize


CATEGORY_FIELDS = ('category_id', 'name', 'description')
PRODUCT_FIELDS = ('product_id', 'price_brl', 'name', 'category_id', 'description',
                  'stock_quantity', 'status', 'specs', 'created_at')


class CatalogDataError(ValueError):
    """Invalid or unreadable catalog snapshot; no partial catalog is returned."""


def _rows(path: Path, table: str, fields: tuple[str, ...]) -> Iterator[tuple[int, dict[str, str]]]:
    try:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream, strict=True)
            if (reader.fieldnames is None or len(reader.fieldnames) != len(fields)
                    or set(reader.fieldnames) != set(fields)):
                raise CatalogDataError(f'{table}: invalid columns')
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise CatalogDataError(f'{table}: row {reader.line_num}: invalid row width')
                yield reader.line_num, row
    except (OSError, UnicodeError, csv.Error):
        raise CatalogDataError(f'{table}: cannot read valid UTF-8 CSV') from None


def _integer(raw: str, *, minimum: int = 1) -> int:
    if not re.fullmatch(r'[0-9]+', raw):
        raise ValueError
    value = int(raw)
    if value < minimum:
        raise ValueError
    return value


def _name(raw: str) -> str:
    if not raw.strip():
        raise ValueError
    return raw.strip()


def _price(raw: str) -> Decimal:
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', raw):
        raise ValueError
    value = Decimal(raw)
    if not value.is_finite() or value < 0:
        raise ValueError
    return value


def _date(raw: str) -> date:
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', raw):
        raise ValueError
    return date.fromisoformat(raw)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    seen_keys: set[str] = set()
    for key, value in pairs:
        normalized_key = _normalize(key)
        if normalized_key in seen_keys:
            raise ValueError
        seen_keys.add(normalized_key)
        result[key] = value
    return result


def _specs(raw: str) -> MappingProxyType[str, str]:
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or any(
        not key.strip() or not isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError
    return MappingProxyType(value)


def _field[T](row: dict[str, str], field: str, parser: Callable[[str], T], line: int) -> T:
    try:
        return parser(row[field])
    except (ValueError, InvalidOperation, RecursionError):
        raise CatalogDataError(f'products: row {line}: invalid {field}') from None


def load_catalog(products_path: Path, categories_path: Path) -> Catalog:
    """Load exact source schemas, rejecting invalid rows, duplicates and orphans.

    Descriptions may be empty and specs may be {}; required cells, prices and
    dates cannot be absent. Specs follow the observed string-to-string schema.
    Prices preserve source Decimal values; no rounding or promotion is applied.
    """
    categories: list[Category] = []
    category_ids: set[int] = set()
    for line, row in _rows(categories_path, 'categories', CATEGORY_FIELDS):
        try:
            category = Category(_integer(row['category_id']), _name(row['name']), row['description'])
            if category.category_id in category_ids:
                raise ValueError
        except ValueError:
            raise CatalogDataError(f'categories: row {line}: invalid value or duplicate ID') from None
        categories.append(category)
        category_ids.add(category.category_id)

    products: list[Product] = []
    product_ids: set[int] = set()
    for line, row in _rows(products_path, 'products', PRODUCT_FIELDS):
        product = Product(
            product_id=_field(row, 'product_id', _integer, line),
            price_brl=_field(row, 'price_brl', _price, line),
            name=_field(row, 'name', _name, line),
            category_id=_field(row, 'category_id', _integer, line),
            description=row['description'],
            stock_quantity=_field(row, 'stock_quantity', lambda raw: _integer(raw, minimum=0), line),
            status=_field(row, 'status', ProductStatus, line),
            specs=_field(row, 'specs', _specs, line),
            created_at=_field(row, 'created_at', _date, line),
        )
        try:
            field = 'product_id'
            if product.product_id in product_ids:
                raise ValueError
            field = 'category_id'
            if product.category_id not in category_ids:
                raise ValueError
        except ValueError:
            raise CatalogDataError(f'products: row {line}: invalid {field} or inconsistent reference') from None
        products.append(product)
        product_ids.add(product.product_id)
    return Catalog(tuple(categories), tuple(products))

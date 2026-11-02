"""Deterministic catalog queries against a validated snapshot, never live stock.

Search uses table prices (no promotions), inclusive price ceilings, accent/case
insensitive substrings for names/categories and exact normalized spec keys/values.
Missing specs never match. Empty results mean no matching listing in this snapshot.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
import unicodedata


class ProductStatus(StrEnum):
    ACTIVE = 'active'
    DISCONTINUED = 'discontinued'
    COMING_SOON = 'coming_soon'


@dataclass(frozen=True, slots=True)
class Category:
    category_id: int
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class Product:
    product_id: int
    price_brl: Decimal
    name: str
    category_id: int
    description: str
    stock_quantity: int
    status: ProductStatus
    specs: Mapping[str, str]
    created_at: date

    @property
    def is_purchasable(self) -> bool:
        """Availability in the supplied snapshot; quantity alone is insufficient."""
        return self.status == ProductStatus.ACTIVE and self.stock_quantity > 0


def serialize_product(product: Product) -> dict[str, object]:
    """Return JSON-safe catalog facts; money stays exact as a decimal string."""
    return {
        'product_id': product.product_id,
        'price_brl': str(product.price_brl),
        'name': product.name,
        'category_id': product.category_id,
        'description': product.description,
        'stock_quantity': product.stock_quantity,
        'status': product.status.value,
        'specs': dict(product.specs),
        'created_at': product.created_at.isoformat(),
        'is_purchasable': product.is_purchasable,
    }


def _normalize(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', value.casefold().strip())
                   if not unicodedata.combining(c))


def _query_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Search text must be a nonempty string')
    return _normalize(value)


@dataclass(frozen=True, slots=True)
class Catalog:
    """Construct through load_catalog to enforce source integrity before querying."""

    categories: tuple[Category, ...]
    products: tuple[Product, ...]

    def search(
        self, *, name: str | None = None, category: str | None = None,
        category_id: int | None = None, max_price: Decimal | None = None,
        specs: Mapping[str, str] | None = None, purchasable_only: bool = True,
    ) -> tuple[Product, ...]:
        """Combine filters with AND; preserve source order, including unavailable
        listings only when explicitly requested for informational lookup.
        Unsupported spec keys raise ValueError; supported keys come from all
        products in this snapshot, independently of the other search filters.
        """
        name_query = _query_text(name) if name is not None else None
        category_query = _query_text(category) if category is not None else None
        if category_id is not None and (type(category_id) is not int or category_id <= 0):
            raise ValueError('category_id must be a positive integer')
        if max_price is not None and (
            not isinstance(max_price, Decimal) or not max_price.is_finite() or max_price < 0
        ):
            raise ValueError('max_price must be a finite nonnegative Decimal')
        if type(purchasable_only) is not bool:
            raise ValueError('purchasable_only must be a boolean')
        if specs is not None and not isinstance(specs, Mapping):
            raise ValueError('specs must be a mapping of strings')
        supported_keys = {_normalize(k) for p in self.products for k in p.specs}
        spec_query = set()
        seen_keys: set[str] = set()
        for key, value in (specs or {}).items():
            normalized_key = _query_text(key)
            if normalized_key in seen_keys:
                raise ValueError('Duplicate normalized specification key')
            seen_keys.add(normalized_key)
            if normalized_key not in supported_keys:
                raise ValueError('Unsupported specification key')
            spec_query.add((normalized_key, _query_text(value)))
        category_names = {c.category_id: _normalize(c.name) for c in self.categories}
        return tuple(p for p in self.products
                     if (not purchasable_only or p.is_purchasable)
                     and (name_query is None or name_query in _normalize(p.name))
                     and (category_id is None or p.category_id == category_id)
                     and (category_query is None or category_query in category_names[p.category_id])
                     and (max_price is None or p.price_brl <= max_price)
                     and spec_query <= {(_normalize(k), _normalize(v))
                                        for k, v in p.specs.items()})

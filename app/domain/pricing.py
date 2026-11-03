"""Exact snapshot pricing; explicit source-backed PIX, no discount stacking."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext

from app.data.promotions import PromotionBook
from app.domain.catalog import Product


@dataclass(frozen=True)
class PixRules:
    percent: Decimal
    source_references: tuple[str, ...]

    def __post_init__(self):
        if (type(self.percent) is not Decimal or self.percent != Decimal('5')
                or type(self.source_references) is not tuple or not self.source_references
                or any(type(ref) is not str or not ref.strip() for ref in self.source_references)):
            raise ValueError('Unverified PIX rule configuration')


def _amount(price: Decimal, percent: Decimal = Decimal('0')) -> str:
    # Do not depend on a caller's Decimal precision or mutate its global context.
    with localcontext() as context:
        context.prec = max(28, len(price.as_tuple().digits) + len(percent.as_tuple().digits) + 8)
        value = price * (Decimal('100') - percent) / Decimal('100')
        return format(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')


@dataclass(frozen=True)
class PricingService:
    promotions: PromotionBook
    pix_rules: PixRules | None = None

    def quote(self, product: Product, payment_method: str | None = None) -> dict:
        if payment_method is not None and payment_method not in ('pix', 'credit_card', 'cash'):
            raise ValueError('Unsupported payment method')
        table = _amount(product.price_brl)
        offer = self.promotions.active_for(product.product_id)
        applied = offer is not None and product.is_purchasable
        promotional = _amount(product.price_brl, offer.discount_percent) if applied else None
        references = [f'catalog-snapshot:product/{product.product_id}']
        if applied:
            references.append(f'promotions-snapshot:promotion/{offer.promotion_id}')
        pix, pix_status = None, 'not_requested'
        if payment_method == 'pix':
            if not product.is_purchasable:
                pix_status = 'unavailable_snapshot'
            elif offer is not None:
                pix_status = 'excluded_promotion'
            elif self.pix_rules is None:
                pix_status = 'policy_unavailable'
            else:
                pix = _amount(product.price_brl, self.pix_rules.percent)
                pix_status = 'applied'
                references.extend(self.pix_rules.source_references)
        return {
            'table_price': table, 'promotional_price': promotional,
            'discount_percent': str(offer.discount_percent) if applied else None,
            'promotion_id': offer.promotion_id if applied else None,
            'promotion_applied': applied, 'pix_price': pix, 'pix_status': pix_status,
            'effective_price': pix or promotional or table, 'payment_method': payment_method,
            'is_purchasable': product.is_purchasable, 'source_references': references,
        }

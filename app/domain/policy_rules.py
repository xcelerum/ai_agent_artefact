"""Customer claims and conservative manual-window guidance, never legal approval."""

from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyAssessment:
    decision: str
    missing_facts: tuple[str, ...]
    window_status: str
    customer_claims: dict
    notice: str = ('Customer statements are unverified. Staff review is required; '
                   'store-manual guidance does not determine statutory rights.')


def validate_context(context: object) -> dict:
    if type(context) is not dict:
        raise ValueError('Expected policy context object')
    booleans = {'is_promotional', 'is_final_sale', 'is_customized', 'unused',
                'original_packaging', 'accessories_complete', 'proof_of_purchase'}
    days = {'days_since_receipt', 'days_since_purchase'}
    enums = {'purchase_channel': ('online', 'store'),
             'reason': ('withdrawal', 'defect', 'preference', 'warranty')}
    if not set(context) <= booleans | days | enums.keys():
        raise ValueError('Unknown policy context field')
    for key, value in context.items():
        if value is None:
            continue
        if key in booleans and type(value) is not bool:
            raise ValueError('Invalid policy condition')
        if key in days and (type(value) is not int or not 0 <= value <= 36500):
            raise ValueError('Invalid stated day count')
        if key in enums and (type(value) is not str or value not in enums[key]):
            raise ValueError('Invalid policy context enum')
    return dict(context)


def context_schema() -> dict:
    properties = {key: {'type': ['boolean', 'null']} for key in (
        'is_promotional', 'is_final_sale', 'is_customized', 'unused',
        'original_packaging', 'accessories_complete', 'proof_of_purchase')}
    properties.update({key: {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 36500}
                       for key in ('days_since_receipt', 'days_since_purchase')})
    properties.update({
        'purchase_channel': {'enum': ['online', 'store', None]},
        'reason': {'enum': ['withdrawal', 'defect', 'preference', 'warranty', None]},
    })
    return {'type': 'object', 'additionalProperties': False, 'properties': properties}


def assess_case(topic: str, context: dict | None, withdrawal_window_verified: bool) -> PolicyAssessment | None:
    if topic not in ('withdrawal', 'returns', 'defect', 'preference', 'warranty'):
        return None
    claims = validate_context({} if context is None else context)
    required = ('purchase_channel', 'days_since_receipt', 'is_customized', 'is_final_sale',
                'unused', 'original_packaging', 'accessories_complete') if topic == 'withdrawal' else (
                    'reason', 'proof_of_purchase')
    missing = tuple(key for key in required if claims.get(key) is None)
    conflicting_reason = (topic in ('withdrawal', 'defect', 'preference')
                          and claims.get('reason') is not None and claims['reason'] != topic)
    if conflicting_reason and 'reason' not in missing:
        missing += ('reason',)
    window = 'unknown'
    if topic == 'withdrawal' and withdrawal_window_verified and not conflicting_reason:
        if claims.get('purchase_channel') == 'store':
            window = 'not_applicable_to_stated_channel'
        elif claims.get('purchase_channel') == 'online' and claims.get('days_since_receipt') is not None:
            window = 'within_stated_window' if claims['days_since_receipt'] <= 7 else 'outside_stated_window'
    return PolicyAssessment('clarification_required' if missing else 'review_required',
                            missing, window, deepcopy(claims))

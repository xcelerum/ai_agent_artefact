"""Local deterministic Portuguese presentation; no model-generated customer facts."""

from decimal import Decimal, localcontext
import re

ACTION_DENIAL = 'Não consigo alterar preços cadastrados nem realizar transações por aqui. Posso consultar as informações oficiais para você.'
CANCELLATION_DENIAL = 'Não posso executar cancelamentos, reembolsos ou transações. Posso explicar as regras e orientar o atendimento.'


MESSAGES = {
    'clarification': 'Qual produto ou situação você quer consultar? Pode dar mais detalhes?',
    'unsupported': 'Aqui no Empório da Música trabalhamos exclusivamente com instrumentos musicais, não com acessórios. Posso ajudar a escolher um instrumento ou consultar as políticas da loja. O que você procura?',
    'invalid_request': 'Não consegui validar os detalhes. Pode reformular a pergunta ou informar o produto?',
    'no_matches': 'Não encontrei opções com esses filtros no catálogo consultado. Quer ajustar o preço ou alguma característica?',
    'model_error': 'Tive uma dificuldade técnica para entender a mensagem. Pode tentar novamente?',
    'tool_error': 'Houve uma falha técnica na consulta. Tente novamente em instantes.',
    'aggregation_error': 'Houve uma falha técnica ao conferir as consultas. Tente novamente.',
    'policy_unavailable': 'Não consegui confirmar essa regra no manual. Posso tentar consultar as regras gerais de devolução, troca e garantia ou os contatos da loja. Qual dessas informações você precisa?',
    'authorization_required': 'Por segurança, dados de pedidos exigem autenticação confiável. Procure o atendimento; não consigo consultar seu pedido por aqui.',
    'failed': 'Não consegui confirmar as informações solicitadas. O atendimento pode ajudar.',
}


def clean(text):
    return ' '.join(''.join(c for c in str(text) if c.isprintable() or c in '\n\t').split())


def brl(value):
    return 'R$ ' + format(Decimal(value), ',.2f').replace(',', '_').replace('.', ',').replace('_', '.')


def _products(products):
    lines = ['Estas são as opções do catálogo (o estoque pode mudar):']
    for index, product in enumerate(products[:5], 1):
        text = f"{index}. {clean(product['name'])} — {brl(product['price_brl'])}"
        text += ' — disponível no catálogo.' if product['is_purchasable'] else ' — indisponível para compra no catálogo.'
        attributes = [('strings', 'Cordas'), ('body_material', 'Corpo'), ('top_material', 'Tampo')]
        for key, label in attributes:
            value = product['specs'].get(key)
            if value is not None:
                value = {'steel': 'aço'}.get(value, value)
                text += f' {label}: {clean(value)}.'
        pricing = product.get('pricing')
        if pricing:
            if pricing['promotion_applied']:
                text += f" Promoção: de {brl(pricing['table_price'])} por {brl(pricing['promotional_price'])} ({clean(pricing['discount_percent'])}% de desconto)."
            if pricing['pix_price'] is not None:
                text += f" No PIX: {brl(pricing['pix_price'])}."
            elif pricing['pix_status'] == 'excluded_promotion':
                text += ' O desconto PIX não acumula com esta promoção.'
            elif pricing['pix_status'] == 'policy_unavailable':
                text += ' Não consegui confirmar o desconto PIX no manual.'
        lines.append(text)
    if len(products) > 5:
        lines.append('Mostrei cinco opções. Posso refinar a busca para você.')
    return '\n'.join(lines)


def _policy_snippets(outcome, hypothetical_defect=False):
    # Rejoin PDF layout lines; quote complete sentences only, never cut conditions.
    blocks, current = {}, None
    for line in outcome.facts.get('text', '').splitlines():
        heading = re.match(r'^(\d+(?:\.\d+)*)\.?\s+', line)
        if heading:
            current = heading[1]
        elif line.strip():
            blocks.setdefault(current, []).append(clean(line))
    snippets = []
    for section, body in blocks.items():
        text = ' '.join(body)
        match = re.match(r'.+?[.!?](?=\s|$)', text)
        refs = [ref for ref in outcome.source_references if section is None or f':section/{section}:' in ref]
        page = next((m[1] for ref in refs if (m := re.search(r':printed-page/(\d+)', ref))), None)
        citation = f"manual, seção {section}, p. {page}" if section and page else 'manual consultado'
        labels = {'4.1': 'Arrependimento', '4.2': 'Se o produto vier com defeito' if hypothetical_defect else 'Defeito',
                  '4.3': 'Troca por preferência', '4.4': 'Condições especiais'}
        label = labels.get(section, 'Orientação da loja')
        if match and len(match[0]) <= 480:
            snippet = f'{label}: “{match[0]}” ({citation})'
        else:
            snippet = f'{label}: encontrei orientações no {citation}; o atendimento pode detalhar as condições completas.'
        snippets.append((section, snippet))
        if len(snippets) == 3:
            break
    return snippets


def _comparison(products):
    text = _products(products)
    available = [p for p in products if p['is_purchasable']]
    def price(product):
        return product.get('pricing', {}).get('effective_price') or product['price_brl']
    if available:
        cheapest = min(available, key=lambda p: Decimal(price(p)))
        text += f"\nSe o critério for menor preço, {clean(cheapest['name'])} tem o menor valor entre as opções disponíveis: {brl(price(cheapest))}."
        if len(available) > 1:
            with localcontext() as context:
                context.prec = max(28, max(len(price(p)) for p in available)+4)
                spread = max(Decimal(price(p)) for p in available) - min(Decimal(price(p)) for p in available)
            text += f' A diferença entre o maior e o menor preço informado é {brl(spread)}.'
    text += ('\nO catálogo não comprova qual é melhor para iniciantes em conforto, som ou facilidade de aprendizado. '
             'Posso comparar os preços e as características cadastradas. Qual é seu orçamento máximo?')
    return text


def _semantic_catalog(outcome):
    request = outcome.facts['request']
    products = outcome.facts.get('products', [])
    has_focus = any(p['product_id'] == outcome.facts.get('focus_product_id') for p in products)
    contextual_explanation = request['response'] == 'clarify' and has_focus and len(products) > 1
    alternative = request['budget'] == 'below_reference' or request['goal'] == 'alternatives'
    if request['response'] == 'clarify' and not contextual_explanation and not alternative:
        return 'O que você gostaria de mudar na busca: preço, tipo de cordas ou outra característica?'
    if outcome.status == 'no_matches':
        return MESSAGES['no_matches']
    if request['reference'] == 'new' and (request['goal'] == 'learn' or request['response'] == 'explain'):
        strings = sorted({clean(p['specs']['strings']) for p in products if 'strings' in p['specs']})
        facts = ', '.join(strings) if strings else 'não informado nesses resultados'
        return (f'O tipo de cordas é uma característica cadastrada. Nos resultados consultados: {facts}. '
                'Isso não comprova conforto, timbre ou facilidade para aprender. Para escolher, compare também '
                'as dimensões e os recursos registrados; experimente o instrumento com orientação quando possível. '
                'Quer filtrar por tipo de cordas e orçamento?')
    if (request['response'] in ('compare', 'recommend') or contextual_explanation
            or request['response'] == 'explain' and request['reference'] in ('selected', 'candidates')):
        text = _comparison(products)
        focus = next((p for p in products if p['product_id'] == outcome.facts.get('focus_product_id')
                      and p['is_purchasable']), None)
        others = [p for p in products if p['is_purchasable'] and p is not focus]
        if focus and others:
            def amount(product):
                return Decimal(product.get('pricing', {}).get('effective_price') or product['price_brl'])
            other = min(others, key=amount)
            with localcontext() as context:
                context.prec = max(28, len(str(amount(focus)))+len(str(amount(other)))+4)
                delta = amount(focus) - amount(other)
            direction = 'a mais' if delta >= 0 else 'a menos'
            text = (f"{clean(focus['name'])} custa {brl(abs(delta))} {direction} que {clean(other['name'])}. "
                    'Essa é uma diferença objetiva de preço, não uma comprovação de qualidade.\n' + text)
        if outcome.facts.get('search_parameters', {}).get('max_price') is not None:
            text = text.replace('Qual é seu orçamento máximo?', 'Além do preço, qual característica é mais importante para você?')
        if request['budget'] == 'below_reference':
            text = 'Estas opções têm preço de tabela menor que o produto de referência, na mesma categoria e tipo de cordas cadastrado.\n' + text
        return text
    text = _products(products)
    if request['budget'] == 'below_reference':
        text = ('Busquei a mesma categoria e o tipo de cordas cadastrado, quando disponível, '
                'com preço de tabela menor que o produto de referência.\n' + text)
    return text


def render_portuguese(reply, *, comparison=False, customer_facts=None, informational=False,
                      hypothetical_defect=False, reported_defect=False):
    customer_facts = customer_facts or {}
    if not reply.task_outcomes:
        hints = {
            'reference': 'Qual produto você quer? Pode indicar uma opção mostrada ou informar o nome?',
            'comparison': 'Quais duas opções você quer comparar? Pode indicar os números ou nomes?',
            'criteria': 'O que você quer priorizar ou mudar: preço, características ou tipo de produto?',
            'budget': 'Qual é o novo limite de preço que você quer usar?',
            'unsupported_action': ACTION_DENIAL,
            'cancellation': CANCELLATION_DENIAL,
            'outside_capability': MESSAGES['unsupported'],
        }
        if reply.clarification in hints:
            return hints[reply.clarification]
        return MESSAGES.get(reply.status, MESSAGES['failed'])
    lines, seen, missing, review = [], set(), set(), False
    if reply.clarification in ('unsupported_action', 'cancellation'):
        lines.append(CANCELLATION_DENIAL if reply.clarification == 'cancellation' else ACTION_DENIAL)
    semantic_catalog = [o for o in reply.task_outcomes if o.domain == 'catalog' and o.facts.get('request')
                        and o.status in ('ok', 'no_matches')]
    if semantic_catalog:
        lines.extend(_semantic_catalog(outcome) for outcome in semantic_catalog)
    elif reply.products:
        lines.append(_comparison(reply.products) if comparison else _products(reply.products))
    for outcome in reply.task_outcomes:
        if outcome.status == 'unsupported' and outcome.error_category == 'unsupported_action':
            if reply.clarification not in ('unsupported_action', 'cancellation'):
                lines.append(CANCELLATION_DENIAL)
            continue
        if outcome.status == 'clarification' and outcome.facts.get('clarification'):
            lines.append('Qual produto você quer consultar ou comparar? Pode indicar uma opção ou informar o nome?')
            continue
        if outcome in semantic_catalog:
            continue
        if outcome.domain == 'catalog' and outcome.status == 'ok':
            continue
        if outcome.domain == 'policy' and outcome.facts.get('text') and outcome.status in ('ok', 'clarification', 'review_required'):
            mode = outcome.facts.get('request', {}).get('situation')
            for key, text in _policy_snippets(outcome, hypothetical_defect or mode == 'hypothetical'):
                identity = key or text
                if identity not in seen:
                    seen.add(identity)
                    lines.append(text)
            assessment = outcome.facts.get('assessment')
            if assessment:
                if mode not in ('general', 'hypothetical'):
                    missing.update(assessment['missing_facts'])
                review = True
            continue
        status = 'tool_error' if outcome.status == 'error' else outcome.status
        text = MESSAGES.get(status, MESSAGES['failed'])
        if text not in seen:
            seen.add(text)
            lines.append(text)
    questions = {
        'purchase_channel': 'A compra foi pela internet ou na loja?',
        'days_since_receipt': 'Há quantos dias você recebeu o produto?',
        'days_since_purchase': 'Há quantos dias foi feita a compra?',
        'reason': 'Você quer trocar por defeito, preferência ou arrependimento?',
        'is_customized': 'O item foi personalizado?', 'is_final_sale': 'O item foi vendido em condição de liquidação final?',
        'unused': 'O produto está sem uso?', 'original_packaging': 'Você tem a embalagem original?',
        'accessories_complete': 'Os acessórios estão completos?', 'proof_of_purchase': 'Você tem o comprovante de compra?',
    }
    missing -= {key for key, value in customer_facts.items() if value is not None}
    if missing and not informational:
        question = next((questions[key] for key in questions if key in missing), None)
        if question:
            lines.append(question)
    if reported_defect and review:
        lines.insert(0, 'Sinto muito pelo problema. Você relatou um defeito; a equipe precisa avaliar o instrumento para orientar os próximos passos.')
    if review:
        lines.append('Essas são orientações gerais. A equipe precisa avaliar as condições do seu caso; não consigo aprovar trocas ou reembolsos por aqui.')
    return '\n'.join(lines)

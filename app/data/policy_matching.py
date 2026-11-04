"""Bounded lexical aids for the existing numbered local-policy index."""

import re
import unicodedata


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold())
                   if not unicodedata.combining(c))


def topics(text):
    text = normalize(text or '').replace('_', ' ')
    aliases = {
        'withdrawal': ('withdrawal', 'arrependimento', 'arrependi', 'desisti', 'voltar atras'),
        'defect': ('defect', 'defeito', 'quebrado', 'nao liga', 'nem liga', 'parou de funcionar'),
        'preference': ('preference', 'preferencia', 'nao gostei', 'outra cor'),
        'returns': ('returns', 'return policy', 'devolucao', 'devolver', 'trocar', 'troca', 'trocas'),
        'shipping': ('shipping', 'frete', 'entrega', 'entregar', 'delivery', 'para chegar', 'rastreamento'),
        'payments': ('payments', 'payment', 'pagamento', 'pagar', 'pix', 'parcelar', 'parcelamento', 'parcelas'),
        'hours': ('hours', 'horario', 'abre', 'fecha'),
        'contacts': ('contacts', 'contact', 'contato', 'telefone'),
        'promotions': ('promotions', 'promocoes', 'discounts', 'descontos'),
        'warranty': ('warranty', 'garantia'), 'privacy': ('privacy', 'privacidade'),
    }
    found = []
    for topic, terms in aliases.items():
        matches = [re.search(r'\b' + re.escape(term) + r'\b', text) for term in terms]
        positions = [m.start() for m in matches if m]
        if positions:
            found.append((min(positions), topic))
    names = [name for _, name in sorted(found)]
    if set(names) & {'withdrawal', 'defect', 'preference'}:
        names = [name for name in names if name != 'returns']
    return tuple(names)


def section_scope(selected, query, mapping):
    required, allowed = [], []
    text = normalize(query or '')
    for topic in selected:
        sections = mapping[topic]
        primary = list(sections[:1])
        if topic == 'returns':
            primary = ['4.1', '4.2', '4.3']
        if query and topic == 'payments':
            primary = ['3'] + (['3.1'] if re.search(r'parcel|installment', text) else [])
            sections = primary
        if query and topic == 'shipping':
            primary = ['5.1']
            if re.search(r'prazo|tempo|para chegar|delivery time', text):
                primary.append('5.2')
            if re.search(r'rastrea|tracking', text):
                primary.append('5.3')
            sections = primary
        required.extend(primary)
        allowed.extend(sections)
    return tuple(dict.fromkeys(required)), tuple(dict.fromkeys(allowed))


def has_body(fragment):
    lines = fragment.text.strip().splitlines()
    return bool(lines) and (len(lines) > 1 or not re.match(r'^\d+(?:\.\d+)*\.?\s', lines[0]))


def bounded(fragments, required):
    """Select whole sections, deduplicate page fragments, cap eight refs/8000 chars."""
    groups, seen = {}, set()
    for fragment in fragments:
        key = (fragment.section, fragment.pdf_page)
        if key not in seen and has_body(fragment):
            groups.setdefault(fragment.section, []).append(fragment)
            seen.add(key)
    selected = []
    # Required sections precede optional supporting sections, preserving ranked ties.
    order = sorted(groups, key=lambda section: section not in required)
    for section in order:
        proposed = [*selected, *groups[section]]
        if len(proposed) <= 8 and len('\n\n'.join(f.text for f in proposed)) <= 8000:
            selected = proposed
    return tuple(selected)


def rank_sections(fragments, allowed, required, query):
    """Rank only allowlisted relevant sections; source text is data, never code."""
    words = set(re.findall(r'\w+', normalize(query or '')))
    candidates = [f for f in fragments if f.section in allowed and has_body(f)]
    candidates.sort(key=lambda f: (f.section not in required,
                    -len(words & set(re.findall(r'\w+', normalize(f.text)))),
                    f.pdf_page, f.section))
    return bounded(candidates, required)

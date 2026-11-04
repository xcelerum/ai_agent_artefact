"""Local section retrieval with explicit page provenance and conservative assessment."""

from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

from app.agent.contracts import PolicyEvidence
from app.domain.policy_rules import assess_case
from app.domain.pricing import PixRules
from app.data.policy_matching import topics, section_scope, bounded, rank_sections, normalize


def _normalize(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold())
                   if not unicodedata.combining(c))


def _topic_sections() -> dict:
    return {'hours': ('2',), 'contacts': ('1.2',), 'payments': ('3', '3.1'),
            'withdrawal': ('4.1', '4.4'), 'returns': ('4.1', '4.2', '4.3', '4.4'),
            'defect': ('4.2', '4.4'), 'preference': ('4.3', '4.4'),
            'shipping': ('5.1', '5.2', '5.3'), 'promotions': ('6.2', '6.1'),
            'warranty': ('8.1', '8.2', '8.3'), 'privacy': ('9',)}


def _topic(topic: str) -> str | None:
    if type(topic) is not str or not topic.strip() or len(topic) > 200:
        return None
    normalized = _normalize(topic).replace('_', ' ').strip()
    aliases = {'hours': ('hours', 'horario'), 'contacts': ('contacts', 'contact', 'contato'),
               'payments': ('payments', 'payment', 'pagamento', 'pix', 'installments'),
               'withdrawal': ('withdrawal', 'arrependimento'),
               'returns': ('returns', 'return policy', 'devolucao', 'trocas'),
               'defect': ('defect', 'defeito'), 'preference': ('preference', 'preferencia'),
               'shipping': ('shipping', 'frete', 'delivery'),
               'promotions': ('promotions', 'promocoes', 'discounts'),
               'warranty': ('warranty', 'garantia'), 'privacy': ('privacy', 'privacidade')}
    matches = {key for key, terms in aliases.items() if any(
        re.search(r'\b' + re.escape(term) + r'\b', normalized) for term in terms)}
    return next(iter(matches)) if len(matches) == 1 else None


@dataclass(frozen=True)
class PolicyFragment:
    section: str
    pdf_page: int
    printed_page: int | None
    text: str


def _index(pages: list[dict]) -> tuple[PolicyFragment, ...]:
    lines_per_page = [[re.sub(r'\s+', ' ',line).strip() for line in page['text'].splitlines()
                       if line.strip()] for page in pages]
    repeated = Counter(line for lines in lines_per_page for line in set(lines))
    roots = {'1': ('sobre', 'store', 'identity'), '2': ('horario', 'hours'),
             '3': ('formas', 'payment'), '4': ('politica de trocas', 'returns'),
             '5': ('politica de frete', 'shipping'), '6': ('promocoes', 'promotions'),
             '7': ('atendimento', 'service'), '8': ('garantia', 'warranty'),
             '9': ('privacidade', 'privacy'), '10': ('disposicoes', 'final')}
    fragments, current = [], None
    for page, lines in zip(pages, lines_per_page):
        buffers = {}
        for line in lines:
            if repeated[line] > 1 or re.search(r'(?i)(?:p[áa]gina|page)\s+\d+\b', line):
                continue
            match = re.match(r'^(\d+(?:\.\d+)*)\.?\s+(.+)', line)
            if match:
                number, title = match.groups()
                valid = (number in roots and _normalize(title).startswith(roots[number])) or (
                    '.' in number and number.split('.')[0] in roots)
                if valid:
                    current = number
            if current:
                buffers.setdefault(current, []).append(line)
        for section, body in buffers.items():
            fragments.append(PolicyFragment(section, page['pdf_page'], page['printed_page'], '\n'.join(body)))
    return tuple(fragments)


@dataclass(frozen=True)
class LocalPolicyService:
    fragments: tuple[PolicyFragment, ...]
    source_id: str
    extraction_failed: bool = False

    @classmethod
    def from_pdf(cls, path: Path):
        try:
            path = Path(path)
            if not 0 < path.stat().st_size <= 10 * 1024 * 1024:
                return cls((), 'unavailable', extraction_failed=True)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            worker = Path(__file__).with_name('_pdf_worker.py')
            completed = subprocess.run([sys.executable, str(worker), str(path)],
                                       capture_output=True, timeout=10, check=True)
            data = json.loads(completed.stdout)
            return cls(_index(data['pages']), f'store-policy:{digest}')
        except FileNotFoundError:
            return cls((), 'unavailable')
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            return cls((), 'unavailable', extraction_failed=True)

    def _references(self, fragments) -> tuple[str, ...]:
        return tuple(f'{self.source_id}:section/{f.section}:pdf-page/{f.pdf_page}:'
                     f'printed-page/{f.printed_page if f.printed_page is not None else "unavailable"}'
                     for f in fragments)

    def _text_for(self, sections: tuple[str, ...]) -> str:
        return '\n'.join(f.text for f in self.fragments if f.section in sections)

    def lookup(self, *, topic: str, context: dict | None = None) -> PolicyEvidence | None:
        # Backward-compatible topic-only evidence interface.
        evidence = self.retrieve(topic=topic, context=context)
        return evidence if evidence.text and evidence.retrieval_status in ('ok', 'clarification_required') else None

    def _fallback(self, allowed, required, query):
        # Exactly one local index pass; no extraction retry or model call.
        return rank_sections(self.fragments, allowed, required, query)

    def retrieve(self, *, topic: str, query: str | None = None,
                 context: dict | None = None) -> PolicyEvidence:
        def unavailable(status, fallback=False):
            return PolicyEvidence('', (), retrieval_status=status, fallback_used=fallback)

        if self.extraction_failed:
            return unavailable('technical_error')
        if type(topic) is not str or len(topic) > 200 or (query is not None and (
                type(query) is not str or len(query) > 4000)):
            return unavailable('clarification_required')
        query_topics = topics(query)
        primary = _topic(topic)
        if (primary in (None, 'returns') and query and not query_topics
                and re.search(r'\b(isso|aquilo|como funciona)\b', normalize(query))):
            return unavailable('clarification_required')
        selected = query_topics or ((primary,) if primary else topics(topic))
        if primary and primary != 'returns':
            # Specific semantic routing is authoritative; lexical topics add coverage.
            selected = tuple(dict.fromkeys((primary, *query_topics)))
        if set(selected) & {'withdrawal', 'defect', 'preference'}:
            selected = tuple(name for name in selected if name != 'returns')
        if not selected or not self.fragments:
            return unavailable('insufficient_evidence')
        required, allowed = section_scope(selected, query, _topic_sections())
        primary_sections = _topic_sections()[primary] if primary else ()
        fragments = bounded((f for f in self.fragments if f.section in allowed
                             and f.section in primary_sections), required)
        fallback = not set(required) <= {f.section for f in fragments}
        if fallback:
            fragments = self._fallback(allowed, required, query or topic)
        if not set(required) <= {f.section for f in fragments}:
            return unavailable('insufficient_evidence', fallback)
        text = '\n\n'.join(f.text for f in fragments)
        withdrawal = _normalize(self._text_for(('4.1',)))
        window_verified = bool(re.search(r'\b7\s*(?:\([^)]*\)\s*)?(?:dias?|days?)\b', withdrawal))
        assessments = [a for name in selected if (a := assess_case(name, context, window_verified))]
        assessment = None
        if assessments:
            missing = tuple(dict.fromkeys(key for a in assessments for key in a.missing_facts))
            assessment = replace(assessments[0], missing_facts=missing,
                                 decision='clarification_required' if missing else 'review_required')
        status = ('clarification_required' if assessment and assessment.missing_facts else 'ok')
        return PolicyEvidence(text, self._references(fragments), assessment,
                              retrieval_status=status, fallback_used=fallback)

    def pricing_rules(self) -> PixRules | None:
        payments = _normalize(self._text_for(('3',)))
        promotions = _normalize(self._text_for(('6.2',)))
        if (not all(term in payments for term in ('pix', '5%', 'tabela', 'vista'))
                or re.search(r'\b(?:no|not|nao|without|sem)\b[^\n]{0,50}5\s*%', payments)
                or not all(term in promotions for term in ('pix', 'nao se aplica', 'promoc', 'cumul'))):
            return None
        fragments = tuple(f for f in self.fragments if f.section in ('3', '6.2'))
        return PixRules(Decimal('5'), self._references(fragments))

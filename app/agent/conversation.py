"""Small per-session context; graph state stays transient and sources stay local."""

from collections import deque
from copy import deepcopy
import re
from uuid import uuid4

from app.agent.portuguese import render_portuguese
from app.agent.contracts import POLICY_TOPICS
from app.domain.catalog import _normalize
from app.domain.policy_rules import validate_context


class Conversation:
    def __init__(self, agent):
        self.agent = agent
        self.reset()

    def reset(self):
        self.session_id = uuid4().hex
        self._ids = ()
        self._candidates = ()
        self._policy_facts = {}
        self._policy_topic = None
        self._search_filters = {}
        self._turns = deque(maxlen=6)

    @property
    def product_ids(self):
        return self._ids

    @property
    def candidate_product_ids(self):
        return self._candidates

    @property
    def policy_facts(self):
        return deepcopy(self._policy_facts)

    @property
    def search_filters(self):
        return deepcopy(self._search_filters)

    @property
    def turns(self):
        return tuple(self._turns)

    def _capture_policy_facts(self, text):
        # Hypothetical clauses are not reports of actual purchase/product conditions.
        actual = re.split(r'\b(?:e se|se|caso)\b', text, maxsplit=1)[0]
        updates = {}
        if not re.search(r'\bnao (?:comprei|foi)\b', actual):
            if re.search(r'comprei (?:pela |por |na )?(?:internet|online)|compra online', actual):
                updates['purchase_channel'] = 'online'
            elif re.search(r'comprei (?:na |pela )?loja|compra na loja fisica', actual):
                updates['purchase_channel'] = 'store'
        days = re.search(r'\brecebi (?:ha |faz )?(\d{1,5}|um|dois|tres|quatro|cinco|seis|sete) dias?\b', actual)
        if days and 'nao recebi' not in actual:
            number = days[1]
            number = int(number) if number.isdigit() else ('um', 'dois', 'tres', 'quatro', 'cinco', 'seis', 'sete').index(number)+1
            if number <= 36500:
                updates['days_since_receipt'] = number
        if re.search(r'me arrependi|quero voltar atras', actual):
            updates['reason'] = 'withdrawal'
        reported_defect = bool(re.search(r'(?:veio|chegou).*(?:com defeito|quebrado)|parou de funcionar', actual))
        if reported_defect:
            updates['reason'] = 'defect'
        conditions = {
            'unused': (r'\bnao usei\b|\bsem uso\b', r'\bja usei\b'),
            'original_packaging': (r'\btenho (?:a )?embalagem original\b', r'\bnao tenho (?:a )?embalagem original\b'),
            'proof_of_purchase': (r'\btenho (?:o )?comprovante\b', r'\bnao tenho (?:o )?comprovante\b'),
            'accessories_complete': (r'\bacessorios (?:estao )?completos\b', r'\bfaltam acessorios\b'),
        }
        for key, (positive, negative) in conditions.items():
            if re.search(negative, actual):
                updates[key] = False
            elif re.search(positive, actual):
                updates[key] = True
        for key, value in validate_context(updates).items():
            self._policy_facts[key] = {'value': value, 'provenance': 'customer_statement'}
        return reported_defect

    def respond(self, message):
        # No trusted transaction association exists: claims belong to this turn only.
        self._policy_facts.clear()
        if type(message) is not str or not message.strip() or len(message) > 4000:
            return 'Pode enviar uma pergunta de até 4.000 caracteres?'
        normalized = _normalize(message)
        # Full-message match keeps independent requests in mixed messages executable.
        standalone_cancellation = re.fullmatch(
            r'cancel[ae]\s+(?:(?:o\s+)?meu\s+)?pedido[.!?]*', normalized)
        if standalone_cancellation or re.search(r'\b(reembolse|estorne)\b|faca (?:o |um )?reembolso', normalized):
            return 'Não consigo cancelar pedidos nem emitir reembolsos por aqui. Posso consultar no manual as regras gerais de devolução, troca e garantia ou as informações de atendimento.'
        reported_defect = self._capture_policy_facts(normalized)
        if getattr(self.agent.model, 'semantic_mode', False):
            return self._respond_semantic(message, reported_defect)
        hypothetical_defect = bool(re.search(r'\b(?:se|caso)\b.*(?:defeito|quebrad|nao funcionar)', normalized))
        informational = hypothetical_defect or not re.search(r'tenho direito|sou elegivel|posso (?:devolver|trocar)|quero voltar atras|meu caso', normalized)
        comparison_request = bool(re.search(r'compar|recomend|entre', normalized)
                                  and re.search(r'\b(esses|estes|essas|estas|aqueles|aquelas|os cinco|as opcoes|lista)\b', normalized))
        comparison = comparison_request and len(self._candidates) >= 2
        ordinal = re.search(r'\b(primeiro|segundo|terceiro|quarto|quinto)\b|opcao\s+(\d+)', normalized)
        reference = bool(ordinal or re.search(r'\b(esse|este|ele|essa opcao)\b|^e (?:no pix|o preco|quanto)', normalized))
        ids = self._candidates if comparison else ()
        if reference and not comparison:
            choices = self._ids or self._candidates
            if ordinal:
                choices = self._candidates
                positions = ('primeiro', 'segundo', 'terceiro', 'quarto', 'quinto')
                index = positions.index(ordinal[1]) if ordinal[1] else int(ordinal[2]) - 1
                choices = choices[index:index+1] if 0 <= index < len(choices) else ()
            if len(choices) != 1:
                return 'Qual produto você quer? Pode dizer o nome ou o número de uma das opções mostradas.'
            ids = choices
        values = {key: item['value'] for key, item in self._policy_facts.items()}
        reply = self.agent.invoke(session_id=self.session_id, message=message, selected_product_ids=ids,
                                  compare_products=bool(comparison), policy_context=values)
        if any(outcome.domain == 'catalog' for outcome in reply.task_outcomes):
            known = {product.product_id for product in self.agent.catalog.products}
            returned = tuple(p['product_id'] for p in reply.products[:5] if p['product_id'] in known)
            if not ids:
                self._candidates = returned
                self._ids = returned if len(returned) == 1 else ()
            elif not comparison:
                self._ids = returned
        self._turns.append((message, self._ids))
        return render_portuguese(reply, comparison=bool(comparison), customer_facts=values,
                                 informational=bool(informational), hypothetical_defect=hypothetical_defect,
                                 reported_defect=reported_defect)

    def _respond_semantic(self, message, reported_defect):
        hypothetical = bool(re.search(r'\b(?:se|caso)\b.*(?:defeito|quebrad|nao funcionar)', _normalize(message)))
        values = {key: item['value'] for key, item in self._policy_facts.items()}
        reply = self.agent.invoke(session_id=self.session_id, message=message,
            selected_product_ids=self._ids, candidate_product_ids=self._candidates,
            previous_filters=self._search_filters, policy_context=values,
            policy_topic=self._policy_topic, semantic_mode=True)
        known = {p.product_id for p in self.agent.catalog.products}
        for outcome in reply.task_outcomes:
            if (outcome.domain == 'policy' and outcome.status in ('ok', 'clarification', 'review_required')
                    and outcome.facts.get('text') and outcome.facts.get('topic') in POLICY_TOPICS):
                self._policy_topic = outcome.facts['topic']
            if outcome.domain == 'catalog' and outcome.status in ('ok', 'no_matches'):
                request = outcome.facts.get('request') or {}
                ids = tuple(p['product_id'] for p in outcome.facts.get('products', [])[:5]
                            if p['product_id'] in known)
                reference = request.get('reference', 'new')
                if (reference in ('new', 'previous_search') or request.get('budget') == 'below_reference'
                        or request.get('goal') == 'alternatives'):
                    self._candidates = ids
                    self._ids = ids if len(ids) == 1 else ()
                    self._search_filters = {k: v for k, v in outcome.facts.get('search_parameters', {}).items()
                                            if k != 'payment_method'}
                elif request.get('response') not in ('compare', 'recommend') and len(ids) == 1:
                    self._ids = ids
            assessment = outcome.facts.get('assessment')
            if assessment and not hypothetical and outcome.facts.get('request', {}).get('situation') == 'individual':
                for key, value in validate_context(assessment['customer_claims']).items():
                    if value is not None:
                        self._policy_facts[key] = {'value': value, 'provenance': 'customer_statement'}
        self._turns.append((message, self._ids))
        return render_portuguese(reply, customer_facts={k:v['value'] for k,v in self._policy_facts.items()},
                                 reported_defect=reported_defect, hypothetical_defect=hypothetical,
                                 informational=hypothetical)

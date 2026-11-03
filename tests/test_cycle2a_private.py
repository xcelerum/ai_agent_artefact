"""Optional local originals: structural assertions only, never source-text output."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from app.agent.catalog_agent import build_agent
from app.data.catalog import load_catalog
from app.data.promotions import load_promotions
from app.data.store_policy import LocalPolicyService
from app.domain.pricing import PricingService


class PrivateSourceSmoke(unittest.TestCase):
    def test_original_sources_and_combined_graph(self):
        root = Path(__file__).resolve().parents[1] / 'data' / 'private'
        paths = [root / ('desafio_tecnico_ai_eng - ' + name + '.csv')
                 for name in ('products', 'categories', 'promotions')]
        policy_path = root / 'políticas_da_loja.pdf'
        if not all(p.is_file() for p in [*paths, policy_path]):
            self.skipTest('Optional original business sources unavailable')
        # Original graph data must not enter external tracing, even if a developer
        # has tracing enabled in their surrounding shell environment.
        with patch.dict(os.environ, {'LANGSMITH_TRACING': 'false', 'LANGCHAIN_TRACING_V2': 'false'}):
            catalog = load_catalog(paths[0], paths[1])
            promotions = load_promotions(paths[2], catalog)
            policy = LocalPolicyService.from_pdf(policy_path)
            rules = policy.pricing_rules()
            self.assertEqual(len(catalog.products), 65)
            self.assertEqual(len(catalog.categories), 9)
            self.assertEqual(len(promotions.records), 25)
            self.assertEqual(sum(p.is_active for p in promotions.records), 4)
            self.assertTrue(rules is not None, 'Original payment evidence not recognized')
            for topic in ('hours', 'contacts', 'payments', 'withdrawal', 'defect',
                          'preference', 'shipping', 'promotions', 'warranty', 'privacy'):
                self.assertTrue(policy.lookup(topic=topic) is not None,
                                'Original topic evidence unavailable')
            withdrawal = policy.lookup(topic='withdrawal')
            self.assertTrue(any('section/4.1:pdf-page/4:printed-page/4' in ref
                                for ref in withdrawal.source_references))
            pricing = PricingService(promotions, rules)
            for product in catalog.products:
                quote = pricing.quote(product, 'pix')
                if promotions.active_for(product.product_id) is not None:
                    self.assertTrue(quote['pix_price'] is None)
                if not product.is_purchasable:
                    self.assertTrue(quote['promotional_price'] is None and quote['pix_price'] is None)

            class FakeModel:
                calls = 0

                def extract(self, *, history, message, schema):
                    self.calls += 1
                    return {'schema_version': '2', 'disposition': 'execute', 'tasks': [
                        {'id': 'catalog', 'intent': 'catalog_lookup', 'parameters': {}},
                        {'id': 'policy', 'intent': 'policy_question', 'parameters': {'topic': 'withdrawal'}},
                    ]}

            model = FakeModel()
            reply = build_agent(catalog=catalog, model=model, policy_service=policy,
                                pricing_service=pricing).invoke(session_id='local-smoke',
                                                                message='Local synthetic request')
            self.assertEqual(model.calls, 1)
            self.assertEqual(reply.status, 'clarification')
            self.assertEqual(len(reply.products), 61)
            self.assertTrue(len(reply.task_outcomes) == 2)

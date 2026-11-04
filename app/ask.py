"""One question against explicit local sources; only extraction uses Groq."""

import argparse
import os
from pathlib import Path

from groq import Groq

from app.agent.catalog_agent import build_agent
from app.agent.groq_model import GroqIntentModel
from app.data.catalog import load_catalog
from app.data.promotions import load_promotions
from app.data.store_policy import LocalPolicyService
from app.domain.pricing import PricingService


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question', help='Customer utterance sent to Groq; do not include secrets or private records')
    parser.add_argument('--products', type=Path, required=True)
    parser.add_argument('--categories', type=Path, required=True)
    parser.add_argument('--promotions', type=Path)
    parser.add_argument('--policy-pdf', type=Path)
    args = parser.parse_args(argv)
    if not args.question.strip() or len(args.question) > 4000:
        print('Please provide a question of 1–4000 characters.')
        return 1
    # This command does not export local source contents through graph tracing.
    os.environ['LANGSMITH_TRACING'] = 'false'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    try:
        catalog = load_catalog(args.products, args.categories)
        policy = LocalPolicyService.from_pdf(args.policy_pdf) if args.policy_pdf else None
        pricing = PricingService(load_promotions(args.promotions, catalog),
                                 policy.pricing_rules() if policy else None) if args.promotions else None
        with Groq(timeout=20.0, max_retries=0) as client:
            reply = build_agent(catalog=catalog, model=GroqIntentModel(client=client),
                                policy_service=policy, pricing_service=pricing).invoke(
                                    session_id='one-question', message=args.question)
        print(f'Status: {reply.status}\n{reply.text}')
        return 1 if reply.status in ('model_error', 'tool_error', 'aggregation_error', 'invalid_request', 'failed') else 0
    except Exception:
        print('The request could not be completed. Check local source configuration and model availability.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

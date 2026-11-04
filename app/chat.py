"""Interactive Portuguese terminal chat with explicit local business sources."""

import argparse
import os
from pathlib import Path

from groq import Groq

from app.agent.catalog_agent import build_agent
from app.agent.conversation import Conversation
from app.agent.groq_model import GroqIntentModel
from app.data.catalog import load_catalog
from app.data.promotions import load_promotions
from app.data.store_policy import LocalPolicyService
from app.domain.pricing import PricingService

WELCOME = 'Oi! Sou o assistente do Empório da Música. Sua música começa aqui. Como posso ajudar?'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--products', type=Path, required=True)
    parser.add_argument('--categories', type=Path, required=True)
    parser.add_argument('--promotions', type=Path)
    parser.add_argument('--policy-pdf', type=Path)
    args = parser.parse_args(argv)
    os.environ['LANGSMITH_TRACING'] = 'false'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    try:
        catalog = load_catalog(args.products, args.categories)
        policy = LocalPolicyService.from_pdf(args.policy_pdf) if args.policy_pdf else None
        # Missing promotion source cannot establish that PIX is non-promotional.
        pricing = PricingService(load_promotions(args.promotions, catalog),
                                 policy.pricing_rules() if policy else None) if args.promotions else None
        with Groq(timeout=20.0, max_retries=0) as client:
            chat = Conversation(build_agent(catalog=catalog, model=GroqIntentModel(client=client, semantic_mode=True),
                                            policy_service=policy, pricing_service=pricing))
            print(WELCOME + '\nUse /novo para recomeçar e /sair para encerrar. Não envie senhas ou dados pessoais.')
            while True:
                try:
                    message = input('Você: ').strip()
                except (EOFError, KeyboardInterrupt):
                    print('\nAté logo!')
                    break
                if message.casefold() in ('/sair', 'sair'):
                    print('Até logo!')
                    break
                if message.casefold() == '/novo':
                    chat.reset()
                    print('Começamos uma nova conversa.\n' + WELCOME)
                elif message:
                    print(chat.respond(message))
        return 0
    except Exception:
        print('Não foi possível iniciar a conversa. Confira as fontes locais e a disponibilidade do serviço.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

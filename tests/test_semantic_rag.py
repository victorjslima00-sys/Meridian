"""
Testes unitarios para o Indice de RAG Semantico Financeiro — Orion Quant
Baseado no Stanford CS229 (Capitulo 16.3 e 16.4 — Semantic Retrieval & RAG)
"""
import pytest
from trading_bot.data.quant.semantic_rag import FinancialSemanticRAG


def test_semantic_rag_indexing_and_search():
    rag = FinancialSemanticRAG()
    
    docs = [
        {"id": "doc_01", "text": "Copom decide elevar a taxa Selic para conter pressoes inflacionarias", "category": "macro"},
        {"id": "doc_02", "text": "Petrobras aprova pagamento de dividendos extraordinarios aos acionistas", "category": "corporate"},
        {"id": "doc_03", "text": "Vale registra recorde de producao de minerio de ferro em Carajas", "category": "operational"},
    ]
    
    rag.index_documents(docs)
    assert len(rag.corpus) == 3
    
    # Busca semantica sobre dividendos e retorno aos acionistas
    results = rag.query("proventos rendimentos petrobras acoes", top_k=1)
    assert len(results) == 1
    assert results[0]["id"] == "doc_02"
    assert results[0]["score"] > 0.0

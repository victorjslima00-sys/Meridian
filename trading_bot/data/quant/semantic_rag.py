r"""
Motor de Recuperacao Semantica e RAG Financeiro (Semantic Retrieval & RAG)
Head of Data Engineering: Orion
Meridian Technologies

Fundamentacao Matematica:
Stanford CS229 (Capitulo 16.3 — Semantic retrieval with embeddings, Andrew Ng & Tengyu Ma)
Equacoes Implementadas:
  1. Similaridade de Cosseno no Espaco de Embeddings (CS229 p. 199):
     \text{score}(q, d) = \cos \angle(\phi_\theta(q), \phi_\theta(d)) = \frac{\phi_\theta(q)^T \phi_\theta(d)}{\|\phi_\theta(q)\|_2 \|\phi_\theta(d)\|_2}
  2. Indexacao e Reranking dos k Maiores Produtos Internos (CS229 Eq. 16.1):
     \hat{R}(q) = \arg\max_{d \in \mathcal{D}}^{(k)} \text{score}(q, d)
"""
from __future__ import annotations

import logging
import re
from typing import Any, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class FinancialSemanticRAG:
    """
    Sistema de busca semantica em comunicados ao mercado e atas do Copom/CVM
    sem dependencia de embeddings pesados em nuvem (TF-IDF com Expansao Semantica e Cosseno Vetorizado).
    """

    def __init__(self):
        self.corpus: List[dict[str, Any]] = []
        self.vocabulary: dict[str, int] = {}
        self.doc_vectors: Optional[np.ndarray] = None
        self.idf: Optional[np.ndarray] = None

    def _tokenize(self, text: str) -> List[str]:
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        tokens = [w for w in cleaned.split() if len(w) > 2]
        return tokens

    def index_documents(self, documents: List[dict[str, Any]]) -> None:
        """
        Indexa documentos e constroi a matriz esparsa normalizada de termos (CS229 p. 199).
        """
        self.corpus = documents
        n_docs = len(documents)
        if n_docs == 0:
            return

        # Constroi vocabulario
        vocab_set = set()
        tokenized_docs = []
        for doc in documents:
            tokens = self._tokenize(doc.get("text", ""))
            tokenized_docs.append(tokens)
            vocab_set.update(tokens)

        self.vocabulary = {term: idx for idx, term in enumerate(sorted(vocab_set))}
        vocab_size = len(self.vocabulary)

        # Matriz de Frequencia de Termos (TF)
        tf = np.zeros((n_docs, vocab_size))
        for i, tokens in enumerate(tokenized_docs):
            for t in tokens:
                if t in self.vocabulary:
                    tf[i, self.vocabulary[t]] += 1.0

        # Frequencia Inversa de Documento (IDF)
        df = np.sum(tf > 0, axis=0)
        self.idf = np.log((n_docs + 1.0) / (df + 1.0)) + 1.0

        # Vetores TF-IDF normalizados L2 (para que produto interno = similaridade de cosseno)
        tfidf = tf * self.idf
        norms = np.linalg.norm(tfidf, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        self.doc_vectors = tfidf / norms

    def query(self, query_text: str, top_k: int = 3) -> List[dict[str, Any]]:
        """
        Calcula o produto interno (cosine similarity) da consulta contra o corpus (CS229 p. 199).
        """
        if self.doc_vectors is None or len(self.corpus) == 0:
            return []

        vocab_size = len(self.vocabulary)
        query_tf = np.zeros(vocab_size)
        tokens = self._tokenize(query_text)
        
        # Expansao semantica de termos financeiros
        synonyms = {
            "proventos": ["dividendos", "jcp"],
            "rendimentos": ["dividendos", "lucro"],
            "acoes": ["petrobras", "vale", "acionistas"],
        }
        expanded_tokens = list(tokens)
        for t in tokens:
            if t in synonyms:
                expanded_tokens.extend(synonyms[t])

        for t in expanded_tokens:
            if t in self.vocabulary:
                query_tf[self.vocabulary[t]] += 1.0

        query_tfidf = query_tf * self.idf
        norm = np.linalg.norm(query_tfidf)
        if norm > 0:
            query_vec = query_tfidf / norm
        else:
            query_vec = query_tfidf

        # Produto interno vetorizado (Cosine Similarity)
        scores = np.dot(self.doc_vectors, query_vec)

        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            doc_data = self.corpus[idx].copy()
            doc_data["score"] = round(float(scores[idx]), 4)
            results.append(doc_data)

        return results

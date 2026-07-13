import asyncio
import re
import chromadb
from config import CHROMA_DIR

chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)


def _get_or_create_collection(doc_id: str):
    return chroma_client.get_or_create_collection(name=doc_id)


async def add_chunks_to_collection(doc_id: str, chunks: list[str], vectors: list[list[float]]) -> None:
    def _call():
        collection = _get_or_create_collection(doc_id)
        ids = [f"{doc_id}-{i}" for i in range(len(chunks))]
        collection.add(ids=ids, embeddings=vectors, documents=chunks)

    await asyncio.to_thread(_call)


def _is_acronym(term: str) -> bool:
    # short, all-uppercase-in-source token like "RAG", "SSE", "API"
    return bool(re.fullmatch(r"[A-Z]{2,6}", term))


def _extract_acronym_terms(question: str) -> list[str]:
    return re.findall(r"\b[A-Z]{2,6}\b", question)


async def query_collection(doc_id: str, question: str, query_vector: list[float], top_k: int = 5) -> list[str]:
    """Returns raw matching chunk strings for a doc_id. Used by the PDF
    gatherer node, which trims/wraps these into Finding objects.
    Vector search with a lexical rerank pass: if the question contains an
    acronym-like term (RAG, SSE, API...), chunks that literally contain that
    exact-case substring are boosted above pure-semantic neighbors. Fixes
    ambiguity between e.g. 'RAG' the acronym and 'rag'/'Rag' as ordinary words,
    which pure embedding similarity can't reliably distinguish."""

    def _call():
        collection = _get_or_create_collection(doc_id)
        # over-fetch candidates so the rerank has room to work
        results = collection.query(query_embeddings=[query_vector], n_results=max(top_k * 3, top_k))
        return results["documents"][0]

    candidates = await asyncio.to_thread(_call)

    acronyms = _extract_acronym_terms(question)
    if not acronyms:
        return candidates[:top_k]

    def has_exact_acronym(chunk: str) -> bool:
        return any(term in chunk for term in acronyms)  # case-sensitive substring match

    boosted = [c for c in candidates if has_exact_acronym(c)]
    rest = [c for c in candidates if not has_exact_acronym(c)]
    return (boosted + rest)[:top_k]

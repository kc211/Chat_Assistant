import asyncio
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import CHUNK_SIZE, CHUNK_OVERLAP


async def extract_text_from_pdf(file_path: str) -> str:
    """pymupdf is sync/CPU-bound — run off the event loop."""

    def _call():
        doc = pymupdf.open(file_path)
        parts = []
        for page_num, page in enumerate(doc):
            parts.append(f"\n\n[Page {page_num + 1}]\n{page.get_text()}")
        doc.close()
        return "".join(parts)

    return await asyncio.to_thread(_call)


async def chunk_text(text: str, doc_title: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Splitter itself is sync/cheap — no need to thread it, but it must NOT
    be awaited (it's a plain constructor, not a coroutine — that was the
    original bug). Each chunk gets a short contextual header prepended before
    embedding, so short acronym-like terms (RAG, SSE, API) keep enough
    surrounding context for retrieval to disambiguate them correctly."""

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    raw_chunks = splitter.split_text(text)

    # dedupe exact repeats (headers/footers repeated per page) and drop empties
    seen = set()
    deduped = []
    for c in raw_chunks:
        stripped = c.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            deduped.append(stripped)

    return [f"[Document: {doc_title}]\n{c}" for c in deduped]

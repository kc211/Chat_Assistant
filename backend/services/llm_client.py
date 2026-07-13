import asyncio
from google import genai
from config import GEMINI_API_KEY, GEMINI_GEN_MODEL, GEMINI_EMBED_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)


async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """Batch-embed text chunks. Runs the sync SDK call in a thread so it
    never blocks the event loop and never mismatches async/sync (a known
    failure mode with this SDK)."""

    def _call():
        result = client.models.embed_content(model=GEMINI_EMBED_MODEL, contents=chunks)
        return [e.values for e in result.embeddings]

    return await asyncio.to_thread(_call)


async def generate_text(prompt: str) -> str:
    """Generic single-prompt generation — used by analyser/writer nodes
    that don't fit the Q&A-over-context shape of generate_answer below."""

    print("inside llm call ")

    def _call():
        response = client.models.generate_content(model=GEMINI_GEN_MODEL, contents=prompt)
        return response.text

    return await asyncio.to_thread(_call)


async def generate_answer(question: str, context_chunks: list[str]) -> str:
    context = "\n\n".join(context_chunks)
    prompt = f"""Answer the question using ONLY the context below.
If the answer isn't in the context, say "I don't know based on this document."

Context:
{context}

Question: {question}

Answer:"""

    def _call():
        response = client.models.generate_content(model=GEMINI_GEN_MODEL, contents=prompt)
        return response.text

    return await asyncio.to_thread(_call)

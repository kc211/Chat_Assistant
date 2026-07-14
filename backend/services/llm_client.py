import asyncio
import logging

from google import genai
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from config import GEMINI_API_KEY, GEMINI_GEN_MODEL, GEMINI_EMBED_MODEL

logger = logging.getLogger("llm")

client = genai.Client(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# One structured error type for the whole backend.
#
# Every LLM/service failure is normalised into this so main.py can turn it
# straight into an SSE "error" event with a stable shape:
#   {type, status, title, message, node, retryable}
# The raw exception is logged server-side only; `message` is user-safe.
# ---------------------------------------------------------------------------
class LLMError(Exception):
    def __init__(self, status, err_type, title, message, retryable):
        self.status = status
        self.type = err_type
        self.title = title
        self.message = message
        self.retryable = retryable
        super().__init__(message)


# Statuses worth retrying: transient server / rate / timeout / network.
# NOT retried: 401, 403, 404 — retrying an auth failure or a bad model id
# just wastes round-trips and delays the error surfacing to the user.
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}


def _classify(exc: Exception) -> LLMError:
    """Map any provider/SDK exception to a structured, user-safe LLMError.

    We inspect whatever the SDK gives us (an HTTP status code if present,
    otherwise the text of the message) and bucket it into a known error.
    The original exception is never exposed to the frontend.
    """
    if isinstance(exc, LLMError):
        return exc

    # Try to dig a numeric HTTP status out of the SDK exception.
    status = (
        getattr(exc, "status_code", None)
        or getattr(exc, "code", None)
        or getattr(getattr(exc, "response", None), "status_code", None)
    )
    text = str(exc).lower()

    # Fall back to sniffing the message when no status attribute exists.
    if status is None:
        if "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text:
            status = 429
        elif "401" in text or "unauthenticated" in text or "api key" in text or "api_key" in text:
            status = 401
        elif "403" in text or "permission" in text:
            status = 403
        elif "404" in text or "not found" in text:
            status = 404
        elif "timeout" in text or "timed out" in text or "deadline" in text:
            status = 408
        elif "503" in text or "unavailable" in text or "overloaded" in text:
            status = 503
        elif "500" in text or "internal" in text:
            status = 500

    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None

    mapping = {
        401: ("auth_error", "Authentication Failed", "Authentication failed. Please verify your API key.", False),
        403: ("permission_error", "Permission Denied", "Permission denied for this model or resource.", False),
        404: ("model_not_found", "Model Not Found", "The requested model was not found.", False),
        408: ("timeout_error", "Request Timed Out", "The model took too long to respond. Please try again.", True),
        429: ("rate_limit_error", "Rate Limit Exceeded", "Rate limit or quota exceeded. Please wait a moment before trying again.", True),
        500: ("llm_error", "Internal Server Error", "The model service hit an internal error. Please try again.", True),
        502: ("llm_error", "Gateway Error", "The model gateway returned an error. Please try again.", True),
        503: ("llm_error", "Model Unavailable", "The model is currently overloaded. Please try again in a few minutes.", True),
        504: ("timeout_error", "Gateway Timeout", "The model gateway timed out. Please try again.", True),
    }

    if status in mapping:
        err_type, title, message, retryable = mapping[status]
        return LLMError(status, err_type, title, message, retryable)

    # Anything we couldn't classify: treat as a transient 503 so it still
    # retries, but never leak the raw text.
    return LLMError(503, "llm_error", "Model Unavailable",
                    "The model service is temporarily unavailable. Please try again.", True)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, LLMError) and exc.status in _RETRYABLE_STATUSES


# Retry only transient LLMErrors: 3 attempts, exponential backoff, then
# re-raise the (already structured) error for the caller to handle.
_llm_retry = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


@_llm_retry
async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """Batch-embed text chunks. Runs the sync SDK call in a thread so it
    never blocks the event loop. Provider failures are normalised to
    LLMError and retried when transient."""

    def _call():
        result = client.models.embed_content(model=GEMINI_EMBED_MODEL, contents=chunks)
        return [e.values for e in result.embeddings]

    try:
        return await asyncio.to_thread(_call)
    except LLMError:
        raise
    except Exception as exc:
        logger.exception("embed_chunks failed")
        raise _classify(exc) from exc


@_llm_retry
async def generate_text(prompt: str) -> str:
    """Generic single-prompt generation used by planner/analyser/writer.
    Provider failures are normalised to LLMError and retried when transient.
    A blocked/empty response (response.text is None) is treated as a
    retryable model error rather than silently returning None downstream."""

    def _call():
        response = client.models.generate_content(model=GEMINI_GEN_MODEL, contents=prompt)
        text = response.text
        if text is None:
            raise LLMError(
                502, "empty_response", "Empty Response",
                "The model returned an empty response. Please try again.", True,
            )
        return text

    try:
        return await asyncio.to_thread(_call)
    except LLMError:
        raise
    except Exception as exc:
        logger.exception("generate_text failed")
        raise _classify(exc) from exc


@_llm_retry
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
        text = response.text
        if text is None:
            raise LLMError(
                502, "empty_response", "Empty Response",
                "The model returned an empty response. Please try again.", True,
            )
        return text

    try:
        return await asyncio.to_thread(_call)
    except LLMError:
        raise
    except Exception as exc:
        logger.exception("generate_answer failed")
        raise _classify(exc) from exc

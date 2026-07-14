import json


def sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def sse_error(exc, node: str | None = None) -> str:
    """Format an SSE 'error' event with the structured shape the frontend
    expects: {type, status, title, message, node, retryable}. Accepts an
    LLMError (carries proper fields) or any exception (bucketed to a generic
    500). Raw exception text is never placed in `message`. `node` falls back
    to any node tagged on the exception itself (exc.node)."""
    status = getattr(exc, "status", 500)
    err_type = getattr(exc, "type", "internal_error")
    title = getattr(exc, "title", "Internal Server Error")
    message = getattr(exc, "message", "Something unexpected happened. Please try again.")
    retryable = getattr(exc, "retryable", False)
    node = node or getattr(exc, "node", None)

    return sse_format("error", {
        "type": err_type,
        "status": status,
        "title": title,
        "message": message,
        "node": node,
        "retryable": retryable,
    })

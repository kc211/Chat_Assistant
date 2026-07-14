from config import TOP_K, MAX_FINDINGS_CHARS
from graph.state import TaskState, add_trace, emit_running, check_step_budget
from services.llm_client import embed_chunks, LLMError
from services.vector_store import query_collection
from db.crud import get_document


async def pdf_gather_core(state: TaskState) -> str:
    """Undecorated retrieval logic — used standalone by gatherer_pdf_node
    and concurrently by gatherer_both_node."""
    doc = await get_document(state["doc_id"])
    if doc is None:
        raise ValueError("Uploaded PDF was not found.")

    vectors = await embed_chunks([state["goal"]])
    chunks = await query_collection(state["doc_id"], state["goal"], vectors[0], top_k=TOP_K)
    return f"[Source: PDF — {doc['filename']}]\n" + "\n\n".join(chunks)[:MAX_FINDINGS_CHARS]


async def gatherer_pdf_node(state: TaskState) -> dict:
    if not check_step_budget(state, "gatherer_pdf"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    await emit_running(state, "gatherer_pdf", "searching uploaded PDF")
    try:
        findings = await pdf_gather_core(state)
        add_trace(state, "gatherer_pdf", "done", "relevant chunks found")
        return {"findings": findings, "step_count": state["step_count"], "trace": state["trace"]}
    except Exception as exc:
        # No degradation: a failed gatherer stops the whole run.
        add_trace(state, "gatherer_pdf", "failed", str(exc))
        if not isinstance(exc, LLMError):
            exc = LLMError(500, "pdf_error", "PDF Search Failed",
                           "Could not search the uploaded PDF.", False)
        exc.node = "gatherer_pdf"
        raise exc

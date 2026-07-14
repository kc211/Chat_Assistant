import asyncio
from config import MAX_FINDINGS_CHARS
from graph.state import TaskState, add_trace, emit_running, check_step_budget
from graph.nodes_pdf import pdf_gather_core
from graph.nodes_web import web_gather_core
from services.llm_client import LLMError


async def gatherer_both_node(state: TaskState) -> dict:
    """Both sources needed (e.g. 'compare my PDF with AWS documentation') —
    run PDF and web retrieval concurrently. No degradation: if EITHER source
    fails, the whole run stops and the UI shows gatherer_both · error."""
    if not check_step_budget(state, "gatherer_both"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    await emit_running(state, "gatherer_both", "gathering PDF and web sources concurrently")

    pdf_result, web_result = await asyncio.gather(
        pdf_gather_core(state), web_gather_core(state), return_exceptions=True
    )

    errors = []
    if isinstance(pdf_result, Exception):
        errors.append(("PDF", pdf_result))
    if isinstance(web_result, Exception):
        errors.append(("Web", web_result))

    if errors:
        detail = "; ".join(f"{label}: {exc}" for label, exc in errors)
        add_trace(state, "gatherer_both", "failed", detail)
        # Surface the first structured error if we have one, else wrap.
        first = next((exc for _, exc in errors if isinstance(exc, LLMError)), None)
        if first is None:
            first = LLMError(502, "gather_error", "Source Gathering Failed",
                             "One or more sources could not be gathered.", True)
        first.node = "gatherer_both"
        raise first

    findings = "\n\n".join([pdf_result, web_result])[:MAX_FINDINGS_CHARS]
    add_trace(state, "gatherer_both", "done", "both sources gathered")
    return {"findings": findings, "step_count": state["step_count"], "trace": state["trace"]}

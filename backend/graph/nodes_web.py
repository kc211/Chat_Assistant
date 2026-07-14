from config import MAX_FINDINGS_CHARS
from graph.state import TaskState, add_trace, emit_running, check_step_budget
from services.search_client import search_web
from services.llm_client import LLMError


async def web_gather_core(state: TaskState) -> str:
    """Undecorated search logic — used standalone by gatherer_web_node and
    concurrently by gatherer_both_node."""
    results = await search_web(state["goal"], max_results=5)
    text = "\n\n".join(f"[Source: Web — {r['url']}] {r['content']}" for r in results)
    return text[:MAX_FINDINGS_CHARS]


async def gatherer_web_node(state: TaskState) -> dict:
    if not check_step_budget(state, "gatherer_web"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    await emit_running(state, "gatherer_web", f"searching web for: {state['goal']}")
    try:
        findings = await web_gather_core(state)
        add_trace(state, "gatherer_web", "done", "results found")
        return {"findings": findings, "step_count": state["step_count"], "trace": state["trace"]}
    except Exception as exc:
        # No degradation: a failed web search stops the whole run (previously
        # this fell back to empty findings + partial — removed per spec).
        add_trace(state, "gatherer_web", "failed", str(exc))
        if not isinstance(exc, LLMError):
            exc = LLMError(502, "web_search_error", "Web Search Failed",
                           "Web search is currently unavailable.", True)
        exc.node = "gatherer_web"
        raise exc

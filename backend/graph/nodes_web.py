from config import MAX_FINDINGS_CHARS
from graph.state import TaskState, add_trace, check_step_budget
from services.search_client import search_web


async def web_gather_core(state: TaskState) -> str:
    """Undecorated search logic — used standalone by gatherer_web_node and
    concurrently by gatherer_both_node."""
    results = await search_web(state["goal"], max_results=5)
    text = "\n\n".join(f"[Source: Web — {r['url']}] {r['content']}" for r in results)
    return text[:MAX_FINDINGS_CHARS]


async def gatherer_web_node(state: TaskState) -> dict:
    if not check_step_budget(state, "gatherer_web"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    add_trace(state, "gatherer_web", "started", f"searching web for: {state['goal']}")
    try:
        findings = await web_gather_core(state)
        add_trace(state, "gatherer_web", "done", "results found")
        print("------ inside tavily")
        print(findings)
        return {"findings": findings, "step_count": state["step_count"], "trace": state["trace"]}
    except Exception as exc:
        # Fallback per assignment: don't crash, don't loop — proceed with
        # empty findings and let the writer report the gap honestly.
        add_trace(state, "gatherer_web", "failed", f"web search unavailable: {exc}")
        return {"findings": "", "step_count": state["step_count"], "trace": state["trace"],
                 "error": f"Web search failed: {exc}"}

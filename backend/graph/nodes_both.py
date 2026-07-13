import asyncio
from config import MAX_FINDINGS_CHARS
from graph.state import TaskState, add_trace, check_step_budget
from graph.nodes_pdf import pdf_gather_core
from graph.nodes_web import web_gather_core


async def gatherer_both_node(state: TaskState) -> dict:
    """Both sources needed (e.g. 'compare my PDF with AWS documentation') —
    run PDF and web retrieval concurrently, not sequentially. If one fails,
    the other's findings still proceed — degraded, not dead."""
    if not check_step_budget(state, "gatherer_both"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    add_trace(state, "gatherer_both", "started", "gathering PDF and web sources concurrently")

    pdf_result, web_result = await asyncio.gather(
        pdf_gather_core(state), web_gather_core(state), return_exceptions=True
    )

    parts, errors = [], []
    if isinstance(pdf_result, Exception):
        errors.append(f"PDF: {pdf_result}")
    else:
        parts.append(pdf_result)

    if isinstance(web_result, Exception):
        errors.append(f"Web: {web_result}")
    else:
        parts.append(web_result)

    if not parts:
        add_trace(state, "gatherer_both", "failed", "; ".join(errors))
        return {"findings": "", "step_count": state["step_count"], "trace": state["trace"],
                 "error": "Both sources failed: " + "; ".join(errors)}

    findings = "\n\n".join(parts)[:MAX_FINDINGS_CHARS]
    detail = "both sources gathered" if not errors else f"partial — {'; '.join(errors)}"
    add_trace(state, "gatherer_both", "done", detail)

    result = {"findings": findings, "step_count": state["step_count"], "trace": state["trace"]}
    if errors:
        result["error"] = "; ".join(errors)
    return result

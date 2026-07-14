import json
from graph.state import TaskState, add_trace, emit_running, check_step_budget
from services.llm_client import generate_text, LLMError


def _safe_parse(raw: str) -> dict:
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(cleaned)
        return {"needs_pdf": bool(data.get("needs_pdf", True)), "needs_web": bool(data.get("needs_web", False))}
    except Exception:
        # Safe fallback: a doc was attached, so default to reading it rather
        # than silently ignoring the attachment.
        return {"needs_pdf": True, "needs_web": False}


async def planner_node(state: TaskState) -> dict:
    """Decides needs_pdf / needs_web by reasoning over the goal text. On an
    LLM failure it raises the structured LLMError (tagged 'planner') so the
    run stops and the UI shows planner · error — no partial fallback."""
    if not check_step_budget(state, "planner"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    await emit_running(state, "planner", "deciding which sources are needed")

    if state["doc_id"] is None:
        add_trace(state, "planner", "done", "no document attached -> web search only")
        return {"needs_pdf": False, "needs_web": True, "step_count": state["step_count"], "trace": state["trace"]}

    prompt = f"""A user has a document attached and asked a question. Decide
which information sources are needed to answer it well.

Question: {state['goal']}

Rules:
- needs_pdf: true if answering requires the attached document's content
- needs_web: true if answering requires external/current information not
  likely to be in the document (e.g. official docs, current facts, or an
  explicit comparison against something outside the document)
- both can be true at once (e.g. "compare my document with AWS's docs")

Respond with ONLY this JSON, no other text:
{{"needs_pdf": true or false, "needs_web": true or false}}"""

    try:
        raw = await generate_text(prompt)
    except LLMError as exc:
        add_trace(state, "planner", "failed", exc.message)
        exc.node = "planner"
        raise

    decision = _safe_parse(raw)

    detail = f"needs_pdf={decision['needs_pdf']}, needs_web={decision['needs_web']}"
    if decision["needs_pdf"] and decision["needs_web"]:
        detail += " (comparison — both gatherers will run)"
    add_trace(state, "planner", "done", detail)

    return {**decision, "step_count": state["step_count"], "trace": state["trace"]}

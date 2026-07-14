from graph.state import TaskState, add_trace, emit_running, check_step_budget
from services.llm_client import generate_text, LLMError


async def writer_node(state: TaskState) -> dict:
    if not check_step_budget(state, "writer"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    await emit_running(state, "writer", "writing final briefing")

    prompt = f"""Write a short, clear answer to the goal below using ONLY the
insights provided. If the insights say no findings were available, say so
plainly instead of making anything up.

Goal: {state['goal']}

Insights:
{state['insights']}

Answer:"""

    try:
        final_result = await generate_text(prompt)
    except LLMError as exc:
        add_trace(state, "writer", "failed", exc.message)
        exc.node = "writer"
        raise

    add_trace(state, "writer", "done", "briefing complete")
    # No partial anymore: reaching here means every node succeeded.
    return {"final_result": final_result, "status": "done", "step_count": state["step_count"], "trace": state["trace"]}

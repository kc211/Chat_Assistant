from graph.state import TaskState, add_trace, check_step_budget


async def writer_node(state: TaskState) -> dict:
    from services.llm_client import generate_text  # local import avoids unused import when budget hits

    if not check_step_budget(state, "writer"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    add_trace(state, "writer", "started", "writing final briefing")

    prompt = f"""Write a short, clear answer to the goal below using ONLY the
insights provided. If the insights say no findings were available, say so
plainly instead of making anything up.

Goal: {state['goal']}

Insights:
{state['insights']}

Answer:"""

    final_result = await generate_text(prompt)
    add_trace(state, "writer", "done", "briefing complete")

    # status: if an earlier node recorded an error but we still produced an
    # answer, call it "partial" (degraded but honest) rather than "done".
    status = "partial" if state.get("error") else "done"

    return {"final_result": final_result, "status": status, "step_count": state["step_count"], "trace": state["trace"]}

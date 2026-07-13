from graph.state import TaskState, add_trace, check_step_budget
from services.llm_client import generate_text


async def analyser_node(state: TaskState) -> dict:
    if not check_step_budget(state, "analyser"):
        return {"step_count": state["step_count"], "status": state["status"], "error": state["error"], "trace": state["trace"]}

    add_trace(state, "analyser", "started", "compressing findings into insights")

    if not state["findings"]:
        insights = "No findings were retrieved. Proceeding with general knowledge only — treat the answer as unverified."
        add_trace(state, "analyser", "done", "no findings to analyse")
        return {"insights": insights, "step_count": state["step_count"], "trace": state["trace"]}

    prompt = f"""Extract the key points from these findings as short bullet points.
If findings come from multiple sources (marked [Source: ...]), compare them
explicitly and note any agreements or contradictions between them. Be concise
— this replaces the raw findings for everything downstream.

Goal: {state['goal']}

Findings:
{state['findings']}

Key points:"""

    insights = await generate_text(prompt)
    add_trace(state, "analyser", "done", "insights produced")
    return {"insights": insights, "step_count": state["step_count"], "trace": state["trace"]}

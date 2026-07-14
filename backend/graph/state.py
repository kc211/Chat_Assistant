from typing import Literal, TypedDict, Callable, Awaitable, Optional
from datetime import datetime, timezone
import asyncio


class TraceEvent(TypedDict):
    step: int
    node: str
    status: Literal["running", "done", "failed", "skipped"]
    detail: str
    timestamp: str


class TaskState(TypedDict):
    goal: str
    doc_id: str | None

    needs_pdf: bool          # decided by the orchestrator's planner, not by "was a file attached"
    needs_web: bool

    findings: str            # plain text, bounded to MAX_FINDINGS_CHARS — whichever gatherer(s) ran
    insights: str              # analyser's compressed output — this, not findings, feeds the writer
    final_result: str

    step_count: int
    max_steps: int
    status: Literal["running", "done", "failed", "partial"]
    error: str | None

    trace: list[TraceEvent]

    # Set by main.py so nodes can push a live "node · running" pill BEFORE
    # they start their (possibly slow / retrying) work. Optional so the
    # graph still runs if nobody wired an emitter (e.g. in tests).
    _emit: Optional[Callable[[dict], Awaitable[None]]]


def new_task_state(goal: str, doc_id: str | None, max_steps: int) -> TaskState:
    return TaskState(
        goal=goal, doc_id=doc_id,
        needs_pdf=False, needs_web=False,
        findings="", insights="", final_result="",
        step_count=0, max_steps=max_steps, status="running", error=None,
        trace=[],
        _emit=None,
    )


def add_trace(state: TaskState, node: str, status: str, detail: str) -> TraceEvent:
    ev = TraceEvent(step=state["step_count"], node=node, status=status, detail=detail,
                    timestamp=datetime.now(timezone.utc).isoformat())
    state["trace"].append(ev)
    return ev


async def emit_running(state: TaskState, node: str, detail: str = "") -> None:
    """Record a 'running' trace entry AND push it to the live stream
    immediately (before the node does its slow work), so the UI shows
    'node · running' during the LLM call and any retries. The frontend keys
    pills by node name and updates the existing pill in place, so emitting
    'running' here and 'done'/'failed' later never creates a second pill."""
    ev = add_trace(state, node, "running", detail)
    emit = state.get("_emit")
    if emit is not None:
        await emit({
            "node": node,
            "status": state.get("status"),
            "trace_tail": ev,
        })


def check_step_budget(state: TaskState, node_name: str) -> bool:
    """Returns True if OK to proceed, False if the step cap was hit.
    Call this at the top of every node — this one check is the entire
    termination guarantee, no decorators needed. NOTE: retries inside a
    node do NOT call this; step_count counts nodes visited, not attempts."""
    state["step_count"] += 1
    if state["step_count"] > state["max_steps"]:
        state["status"] = "failed"
        state["error"] = f"Stopped: reached max_steps ({state['max_steps']}) before {node_name}."
        add_trace(state, node_name, "failed", "step budget exceeded")
        return False
    return True

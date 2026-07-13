from typing import Literal,TypedDict
from datetime import datetime, timezone

class TraceEvent(TypedDict):
    step: int
    node: str
    status: Literal["started", "done", "failed", "skipped"]
    detail: str
    timestamp: str


class TaskState(TypedDict):
    goal:str
    doc_id:str

    needs_pdf:bool
    needs_web:bool

    findings:str
    insights:str
    final_result:str

    step_count:int
    max_steps:int
    status:Literal["running","partial","failed","done"]
    error: str | None

    trace:list[TraceEvent]

def add_trace(state: TaskState, node: str, status: str, detail: str) -> None:
    state["trace"].append(
        TraceEvent(step=state["step_count"], node=node, status=status, detail=detail,
                   timestamp=datetime.now(timezone.utc).isoformat())
    )

def new_task_state(goal:str,doc_id: str | None ,MAX_STEPS:int) -> TaskState:
    return TaskState(
        goal=goal,doc_id=doc_id,
        needs_pdf=False,needs_web=False,
        findings="",insights="",final_result="",
        step_count=0,max_steps=MAX_STEPS,status="running",error=None,
        Trace=[]
    )


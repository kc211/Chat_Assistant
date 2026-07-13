from langgraph.graph import StateGraph, END

from graph.state import TaskState
from graph.planner import planner_node
from graph.nodes_pdf import gatherer_pdf_node
from graph.nodes_web import gatherer_web_node
from graph.nodes_both import gatherer_both_node
from graph.nodes_analyser import analyser_node
from graph.nodes_writer import writer_node

def route_after_planner(state: TaskState) -> str:
    if state["status"] == "partial":
        return END
    if state["needs_pdf"] and state["needs_web"]:
        return "gatherer_both"
    if state["needs_pdf"]:
        return "gatherer_pdf"
    return "gatherer_web"


def after_gather_or_analyser(state: TaskState) -> str:
    """Shared checkpoint: stop immediately if the step budget was hit —
    the entire loop/cost guard lives here."""
    return END if state["status"] == "partial" else "continue"

def build_graph():
    graph= StateGraph(TaskState)

    graph.add_node("planner", planner_node)
    graph.add_node("gatherer_pdf", gatherer_pdf_node)
    graph.add_node("gatherer_web", gatherer_web_node)
    graph.add_node("gatherer_both", gatherer_both_node)
    graph.add_node("analyser", analyser_node)
    graph.add_node("writer", writer_node)

    graph.set_entry_node("planner")

    graph.add_conditional_edges("planner",route_after_planner,
     {"gatherer_pdf": "gatherer_pdf", "gatherer_web": "gatherer_web", "gatherer_both": "gatherer_both", END: END})

    for gather_node in ("gatherer_pdf", "gatherer_web", "gatherer_both"):
        graph.add_conditional_edges(gather_node, after_gather_or_analyser, {"continue": "analyser", END: END})
    graph.add_conditional_edges("analyser", after_gather_or_analyser, {"continue": "writer", END: END})
    graph.add_edge("writer", END)

    return graph.compile()


compiled_graph = build_graph()
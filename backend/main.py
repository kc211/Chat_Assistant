import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import MAX_STEPS, UPLOAD_DIR
from db.session import open_pool, close_pool
from db.crud import save_document, create_task, update_task
from services.pdf_ingest import extract_text_from_pdf, chunk_text
from services.llm_client import embed_chunks
from services.vector_store import add_chunks_to_collection
from graph.state import new_task_state
from graph.orchestrator import compiled_graph
from streaming.sse import sse_format, sse_error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    yield
    await close_pool()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(goal: str = Form(...), file: UploadFile | None = File(None), doc_id: str | None = Form(None)):
    """Single endpoint: send a goal, optionally attach a new PDF (ingested
    inline), or reference a previously-attached one via doc_id. Streams the
    orchestrator run over SSE, including live 'node · running' pills."""


    file_bytes = await file.read() if file is not None else None
    file_name = file.filename if file is not None else None

    async def event_generator():
        nonlocal doc_id

        task_id = str(uuid.uuid4())

        # -------------------------------
        # Inline PDF ingestion 

        if file_bytes is not None:
            yield sse_format("node_update", {"node": "ingest_pdf", "status": "running", "trace_tail": {
                "step": 0, "node": "ingest_pdf", "status": "running", "detail": "ingesting PDF"}})
            try:
                new_doc_id = str(uuid.uuid4())
                file_path = os.path.join(UPLOAD_DIR, f"{new_doc_id}.pdf")
                with open(file_path, "wb") as buffer:
                    buffer.write(file_bytes)

                full_text = await extract_text_from_pdf(file_path)
                chunks = await chunk_text(full_text, doc_title=file_name)
                vectors = await embed_chunks(chunks)
                await add_chunks_to_collection(new_doc_id, chunks, vectors)
                await save_document(new_doc_id, file_name, file_path, len(chunks))
                doc_id = new_doc_id
            except Exception as exc:
                logger.exception("PDF ingestion failed")
                try:
                    await create_task(task_id, goal, doc_id)
                    await update_task(task_id, "failed", None, "PDF ingestion failed.", [])
                except Exception:
                    logger.exception("failed to record failed ingestion task")
                yield sse_format("node_update", {"node": "ingest_pdf", "status": "failed", "trace_tail": {
                    "step": 0, "node": "ingest_pdf", "status": "failed", "detail": "ingestion failed"}})
                yield sse_error(exc, node="ingest_pdf")
                return  # stop — no trailing task_complete

            yield sse_format("node_update", {"node": "ingest_pdf", "status": "done", "trace_tail": {
                "step": 0, "node": "ingest_pdf", "status": "done", "detail": "PDF ingested"}})
            yield sse_format("doc_ingested", {"doc_id": doc_id, "filename": file_name})

        # -------------------------------
        # Create task

        state = new_task_state(goal, doc_id, MAX_STEPS)

        try:
            await create_task(task_id, goal, doc_id)
        except Exception as exc:
            logger.exception("failed to create task row")
            yield sse_error(exc, node="database")
            return

        yield sse_format("task_started", {"task_id": task_id})

        # -------------------------------
        # Run the graph, streaming live 'running' pills via a queue.
        #
        # Nodes push a 'node · running' event through state["_emit"] BEFORE
        # their slow work (so the loader shows during LLM calls / retries).
        # The graph's own per-node output yields the 'done'/'failed' pills.
        # Both flow through one queue drained here. The frontend keys pills by
        # node name and updates in place -> exactly one pill per node.

        queue: asyncio.Queue = asyncio.Queue()

        async def emit(payload: dict) -> None:
            await queue.put(("node_update", payload))

        state["_emit"] = emit

        async def run_graph():
            try:
                async for step_output in compiled_graph.astream(state):
                    for node_name, update in step_output.items():
                        state.update(update)
                        await queue.put(("node_update", {
                            "node": node_name,
                            "status": state.get("status"),
                            "trace_tail": state["trace"][-1] if state["trace"] else None,
                        }))
                await queue.put(("__done__", None))
            except Exception as exc:  # a node raised -> stop the whole run
                await queue.put(("__error__", exc))

        task = asyncio.create_task(run_graph())

        try:
            while True:
                kind, payload = await queue.get()

                if kind == "node_update":
                    yield sse_format("node_update", payload)
                    continue

                if kind == "__error__":
                    exc = payload
                    logger.exception("graph execution failed", exc_info=exc)
                    state["status"] = "failed"
                    state["error"] = getattr(exc, "message", "Task execution failed.")
                    failed_node = getattr(exc, "node", None)
                    # Emit the failing node's pill (running -> failed) BEFORE the
                    # error frame, so the pill flips even without frontend help.
                    if failed_node:
                        yield sse_format("node_update", {
                            "node": failed_node,
                            "status": "failed",
                            "trace_tail": {"step": state.get("step_count", 0), "node": failed_node,
                                           "status": "failed", "detail": state["error"]},
                        })
                    try:
                        await update_task(task_id, "failed", state.get("final_result"),
                                          state["error"], state["trace"])
                    except Exception:
                        logger.exception("failed to persist failed task")
                    yield sse_error(exc, node=failed_node)
                    return  # no trailing task_complete

                if kind == "__done__":
                    break
        finally:
            if not task.done():
                task.cancel()

        # -------------------------------
        # Success path only (every node succeeded)

        try:
            await update_task(task_id, state["status"], state.get("final_result"),
                              state.get("error"), state["trace"])
        except Exception as exc:
            logger.exception("failed to persist completed task")
            yield sse_error(exc, node="database")
            return

        yield sse_format("task_complete", {
            "task_id": task_id, "status": state["status"],
            "final_result": state.get("final_result"), "error": state.get("error"),
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")
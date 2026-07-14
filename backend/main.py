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


@app.post("/chat")
async def chat(
    goal: str = Form(...),
    file: UploadFile | None = File(None),
    doc_id: str | None = Form(None),
):
    """
    Single endpoint:
    - Accepts a goal.
    - Optionally accepts a PDF.
    - Streams node execution back using SSE.
    """

    file_path = None
    filename = None

    if file is not None:
        new_doc_id = str(uuid.uuid4())
        file_path = os.path.join(UPLOAD_DIR, f"{new_doc_id}.pdf")
        filename = file.filename

        file_bytes = await file.read()

        with open(file_path, "wb") as buffer:
            buffer.write(file_bytes)

        doc_id = new_doc_id

    async def event_generator():
        nonlocal doc_id

        # A task_id is created up front so that a failure ANYWHERE below
        # (including PDF ingestion) can still be recorded as "failed" in the
        # DB and reported to the client, then the stream closed cleanly.
        task_id = str(uuid.uuid4())

        # -------------------------------
        # PDF ingestion (now fully guarded)

        if file_path is not None:
            yield sse_format(
                "node_update",
                {"node": "ingest_pdf", "status": "started", "trace_tail": None},
            )

            try:
                full_text = await extract_text_from_pdf(file_path)
                chunks = await chunk_text(full_text, doc_title=filename)
                vectors = await embed_chunks(chunks)
                await add_chunks_to_collection(doc_id, chunks, vectors)
                await save_document(doc_id, filename, file_path, len(chunks))
            except Exception as exc:
                # Full traceback stays server-side; client gets a clean event.
                logger.exception("PDF ingestion failed")
                # Best-effort: record the failed task without crashing further.
                try:
                    await create_task(task_id, goal, doc_id)
                    await update_task(task_id, "failed", None,
                                      "PDF ingestion failed.", [])
                except Exception:
                    logger.exception("failed to record failed ingestion task")
                yield sse_error(exc, node="ingest_pdf")
                return  # stop the stream — no trailing task_complete

            yield sse_format(
                "doc_ingested",
                {"doc_id": doc_id, "filename": filename},
            )

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
        # Execute LangGraph

        try:
            logger.info("Starting graph execution")

            async for step_output in compiled_graph.astream(state):
                for node_name, update in step_output.items():
                    state.update(update)

                    yield sse_format(
                        "node_update",
                        {
                            "node": node_name,
                            "status": state.get("status"),
                            "trace_tail": state["trace"][-1] if state["trace"] else None,
                        },
                    )

        except Exception as exc:
            # A node raised (e.g. LLM 503/429/etc.). Mark failed, tell the
            # client with a structured error, and close the stream. We do
            # NOT fall through to task_complete — that trailing event was
            # what produced the empty/duplicate assistant bubble.
            logger.exception("graph execution failed")
            state["status"] = "failed"
            state["error"] = getattr(exc, "message", "Task execution failed.")

            failed_node = getattr(exc, "node", None)
            try:
                await update_task(task_id, "failed", state.get("final_result"),
                                  state["error"], state["trace"])
            except Exception:
                logger.exception("failed to persist failed task")

            yield sse_error(exc, node=failed_node)
            return

        # -------------------------------
        # Save final task (success / partial path only)

        try:
            await update_task(
                task_id,
                state["status"],
                state.get("final_result"),
                state.get("error"),
                state["trace"],
            )
        except Exception as exc:
            logger.exception("failed to persist completed task")
            yield sse_error(exc, node="database")
            return

        yield sse_format(
            "task_complete",
            {
                "task_id": task_id,
                "status": state["status"],
                "final_result": state.get("final_result"),
                "error": state.get("error"),
            },
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@app.get("/")
async def root():
    return {"message": "Multi-agent research assistant backend is up"}

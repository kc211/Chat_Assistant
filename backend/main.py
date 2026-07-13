import os
import shutil
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
from streaming.sse import sse_format


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

        # -------------------------------
        # PDF ingestion

        if file_path is not None:
            yield sse_format(
                "node_update",
                {
                    "node": "ingest_pdf",
                    "status": "started",
                    "trace_tail": None,
                },
            )

            full_text = await extract_text_from_pdf(file_path)
            chunks = await chunk_text(full_text, doc_title=filename)
            vectors = await embed_chunks(chunks)

            await add_chunks_to_collection(doc_id, chunks, vectors)
            await save_document(
                doc_id,
                filename,
                file_path,
                len(chunks),
            )

            yield sse_format(
                "doc_ingested",
                {
                    "doc_id": doc_id,
                    "filename": filename,
                },
            )

        # -------------------------------
        # Create task

        task_id = str(uuid.uuid4())

        state = new_task_state(
            goal,
            doc_id,
            MAX_STEPS,
        )

        await create_task(
            task_id,
            goal,
            doc_id,
        )

        yield sse_format(
            "task_started",
            {
                "task_id": task_id,
            },
        )

        # -------------------------------
        # Execute LangGraph
 
        try:
            print("Starting graph execution")

            async for step_output in compiled_graph.astream(state):
                print(step_output)

                for node_name, update in step_output.items():
                    state.update(update)

                    yield sse_format(
                        "node_update",
                        {
                            "node": node_name,
                            "status": state.get("status"),
                            "trace_tail": state["trace"][-1]
                            if state["trace"]
                            else None,
                        },
                    )

        except Exception as exc:
            state["status"] = "failed"
            state["error"] = str(exc)

            yield sse_format(
                "error",
                {
                    "message": str(exc),
                },
            )

        # -------------------------------
        # Save final task

        await update_task(
            task_id,
            state["status"],
            state.get("final_result"),
            state.get("error"),
            state["trace"],
        )

        yield sse_format(
            "task_complete",
            {
                "task_id": task_id,
                "status": state["status"],
                "final_result": state.get("final_result"),
                "error": state.get("error"),
            },
        )
        print( "task_id", task_id,
                "status", state["status"],
                "final_result", state.get("final_result"),
                "error", state.get("error"),
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@app.get("/")
async def root():
    return {
        "message": "Multi-agent research assistant backend is up"
    }
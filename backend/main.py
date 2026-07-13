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
async def chat(goal: str= Form(...), file: UploadFile | None = Form(None) , doc_id: str | None = Form(None)):

    if file is not None:
            new_doc_id = str(uuid.uuid4())
            file_path = os.path.join(UPLOAD_DIR, f"{new_doc_id}.pdf")
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            yield sse_format("node_update", {"node": "ingest_pdf", "status": "started", "trace_tail": None})
            full_text = await extract_text_from_pdf(file_path)
            chunks = await chunk_text(full_text, doc_title=file.filename)
            vectors = await embed_chunks(chunks)
            await add_chunks_to_collection(new_doc_id, chunks, vectors)
            await save_document(new_doc_id, file.filename, file_path, len(chunks))
            doc_id = new_doc_id
            yield sse_format("doc_ingested", {"doc_id": doc_id, "filename": file.filename})

    task_id= str(uuid.uuid4())
    state= new_task_state(goal, doc_id,MAX_STEPS)
    await create_task(task_id,goal,doc_id) #for the db records




@app.get("/")
async def root():
    return {"message": "Multi-agent research assistant backend is up"}

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from graph.state import new_task_state
from config import MAX_STEPS,UPLOAD_DIR
import uuid
import os
import shutil




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
    task_id= str(uuid.uuid4())
    await new_task_state(goal, doc_id,MAX_STEPS)




@app.get("/")
async def root():
    return {"message": "Multi-agent research assistant backend is up"}

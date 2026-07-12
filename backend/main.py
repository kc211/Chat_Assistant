from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.session import open_pool, close_pool
from api.routes_upload import router as upload_router
from api.routes_tasks import router as tasks_router


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

app.include_router(upload_router)
app.include_router(tasks_router)


@app.get("/")
async def root():
    return {"message": "Multi-agent research assistant backend is up"}

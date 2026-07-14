import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Web search uses the Brave Search API (free tier, ~2k calls/month).
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
# Deprecated: kept only so any lingering import does not break. Unused.
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

SERPER_API_KEY =os.getenv("SERPER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/research_agent")

UPLOAD_DIR = "uploads"
CHROMA_DIR = "./chroma_db"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
TOP_K = 5

GEMINI_GEN_MODEL = "gemini-3.1-flash-lite"
GEMINI_EMBED_MODEL = "gemini-embedding-001"

MAX_STEPS = 5              # planner + gatherer(s) + analyser + writer = 4 steps; 5 gives headroom
MAX_FINDINGS_CHARS = 4000   # bounds how much gatherer text ever enters the LLM context

os.makedirs(UPLOAD_DIR, exist_ok=True)

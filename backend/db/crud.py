import json
from db.session import pool


async def save_document(doc_id: str, filename: str, file_path: str, num_chunks: int) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO documents (doc_id, filename, file_path, num_chunks) VALUES (%s, %s, %s, %s)",
            (doc_id, filename, file_path, num_chunks),
        )


async def get_document(doc_id: str | None) -> dict | None:
    if doc_id is None:
        return None
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT doc_id, filename, file_path, num_chunks FROM documents WHERE doc_id = %s", (doc_id,)
        )
        row = await cur.fetchone()
        return None if row is None else {"doc_id": row[0], "filename": row[1], "file_path": row[2], "num_chunks": row[3]}


async def create_task(task_id: str, goal: str, doc_id: str | None) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO tasks (task_id, goal, doc_id, status, trace) VALUES (%s, %s, %s, 'running', '[]')",
            (task_id, goal, doc_id),
        )


async def update_task(task_id: str, status: str, final_result: str | None, error: str | None, trace: list[dict]) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE tasks SET status=%s, final_result=%s, error=%s, trace=%s, updated_at=now() WHERE task_id=%s",
            (status, final_result, error, json.dumps(trace), task_id),
        )


async def get_task(task_id: str) -> dict | None:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT task_id, goal, doc_id, status, final_result, error, trace, created_at FROM tasks WHERE task_id=%s",
            (task_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return {"task_id": row[0], "goal": row[1], "doc_id": row[2], "status": row[3],
                "final_result": row[4], "error": row[5], "trace": row[6], "created_at": row[7].isoformat()}


async def list_tasks() -> list[dict]:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT task_id, goal, status, created_at FROM tasks ORDER BY created_at DESC")
        rows = await cur.fetchall()
        return [{"task_id": r[0], "goal": r[1], "status": r[2], "created_at": r[3].isoformat()} for r in rows]

from psycopg_pool import AsyncConnectionPool
from config import DATABASE_URL

pool = AsyncConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=10, open=False)


async def open_pool():
    await pool.open()


async def close_pool():
    await pool.close()

"""
TMCELL Bot - База данных модули
SQLite аркалы улланыҗы маглуматларыны сакламак
"""

import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


async def init_db():
    """Маглуматлар базасыны башлатмак ве таблицалары дөретмек"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                phone_number TEXT,
                password TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS balance_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                balance TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()


async def save_user(user_id: int, phone_number: str, password: str):
    """Улланыҗы маглуматларыны сакламак я-да тәзелемек"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, phone_number, password, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                phone_number = excluded.phone_number,
                password = excluded.password,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, phone_number, password))
        await db.commit()


async def get_user(user_id: int):
    """Улланыҗы маглуматларыны алмак"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, phone_number, password FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "phone_number": row[1],
                    "password": row[2]
                }
            return None


async def delete_user(user_id: int):
    """Улланыҗы маглуматларыны өчүрмек"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM balance_history WHERE user_id = ?", (user_id,))
        await db.commit()


async def save_balance_check(user_id: int, balance: str):
    """Баланс барлаг тарыхыны сакламак"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO balance_history (user_id, balance) VALUES (?, ?)",
            (user_id, balance)
        )
        await db.commit()


async def get_last_balance(user_id: int):
    """Иң соңкы баланс барлагыны алмак"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT balance, checked_at FROM balance_history WHERE user_id = ? ORDER BY checked_at DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"balance": row[0], "checked_at": row[1]}
            return None

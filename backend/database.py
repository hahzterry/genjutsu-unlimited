"""SQLite account storage via aiosqlite."""
import os
from datetime import datetime
from typing import Optional
import aiosqlite

DB_PATH = os.getenv("DB_PATH", "accounts.db")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT NOT NULL UNIQUE,
                password    TEXT NOT NULL,
                credits     INTEGER DEFAULT 1,
                created_at  TEXT NOT NULL,
                last_used   TEXT,
                status      TEXT DEFAULT 'active'
            )
            """
        )
        await db.commit()


async def save_account(email: str, password: str, credits: int = 1) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (email,password,credits,created_at,status) "
            "VALUES (?,?,?,?, 'active')",
            (email, password, credits, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_account_with_credits() -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM accounts WHERE credits > 0 AND status='active' "
            "ORDER BY last_used IS NOT NULL, last_used ASC LIMIT 1"
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def mark_used(email: str, credits_left: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET credits=?, last_used=? WHERE email=?",
            (credits_left, datetime.utcnow().isoformat(), email),
        )
        await db.commit()


async def list_accounts() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM accounts ORDER BY id DESC")
        return [dict(r) for r in await cur.fetchall()]

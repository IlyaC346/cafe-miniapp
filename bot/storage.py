"""Хранение заказов в SQLite."""

import json
from dataclasses import asdict

import aiosqlite

from bot.orders import Order

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    user_name  TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'new',
    total      INTEGER NOT NULL,
    snapshot   TEXT    NOT NULL,  -- заказ целиком: состав по ценам на момент заказа
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id);
"""

# действие администратора → (новый статус, из каких статусов разрешено)
TRANSITIONS = {
    "accept": ("accepted", {"new"}),
    "deliver": ("delivering", {"accepted"}),
    "ready": ("ready", {"accepted"}),
    "done": ("done", {"delivering", "ready"}),
    "cancel": ("cancelled", {"new", "accepted"}),
}


class Storage:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def create(self, user_id: int, user_name: str, order: Order) -> int:
        cur = await self.conn.execute(
            "INSERT INTO orders (user_id, user_name, total, snapshot) VALUES (?, ?, ?, ?)",
            (user_id, user_name, order.total, json.dumps(asdict(order), ensure_ascii=False)),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get(self, order_id: int) -> tuple[aiosqlite.Row, Order] | None:
        async with self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
        return (row, Order(**json.loads(row["snapshot"]))) if row else None

    async def apply(self, order_id: int, action: str) -> str | None:
        """Меняет статус, если переход разрешён. Возвращает новый статус или None."""
        new_status, allowed = TRANSITIONS[action]
        placeholders = ",".join("?" * len(allowed))
        cur = await self.conn.execute(
            f"UPDATE orders SET status = ? WHERE id = ? AND status IN ({placeholders})",
            (new_status, order_id, *allowed),
        )
        await self.conn.commit()
        return new_status if cur.rowcount else None

    async def user_orders(self, user_id: int, limit: int = 5) -> list[tuple[aiosqlite.Row, Order]]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
        return [(r, Order(**json.loads(r["snapshot"]))) for r in rows]

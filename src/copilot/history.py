"""PostgreSQL history and a durable journal for turns that call ONB."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class Turn:
    key: str
    input: dict
    reply: dict | None


class History:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    async def connect(self):
        return await AsyncConnection.connect(self.dsn, autocommit=True, row_factory=dict_row)

    async def initialize(self) -> None:
        async with await self.connect() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(1354921809, 1)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS copilot_conversations (
                    id text PRIMARY KEY, merchant_id text NOT NULL,
                    view jsonb NOT NULL, dialogue jsonb NOT NULL
                )
                """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS copilot_conversations_by_owner
                ON copilot_conversations (merchant_id, (view->>'updated_at') DESC)
                """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS copilot_turns (
                    conversation_id text NOT NULL REFERENCES copilot_conversations(id),
                    key text NOT NULL, input jsonb NOT NULL, reply jsonb,
                    PRIMARY KEY (conversation_id, key)
                )
                """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS copilot_one_pending_turn
                ON copilot_turns (conversation_id) WHERE reply IS NULL
                """)

    async def create(self, cid: str, owner: str, view: dict, dialogue: dict) -> bool:
        async with await self.connect() as conn:
            cur = await conn.execute(
                "INSERT INTO copilot_conversations VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (cid, owner, Jsonb(view), Jsonb(dialogue)),
            )
            return cur.rowcount == 1

    async def list(self, owner: str) -> list[dict]:
        async with await self.connect() as conn:
            cur = await conn.execute("""
                SELECT id, view->>'shop_name' AS shop_name, view->>'status' AS status,
                    view->>'review_id' AS review_id, view->>'updated_at' AS updated_at
                FROM copilot_conversations WHERE merchant_id = %s
                ORDER BY updated_at DESC, id
                """, (owner,))
            return await cur.fetchall()

    @asynccontextmanager
    async def conversation(self, cid: str, owner: str) -> AsyncIterator[ConversationHistory | None]:
        async with await self.connect() as conn:
            cur = await conn.execute(
                "SELECT view, dialogue FROM copilot_conversations WHERE id = %s AND merchant_id = %s",
                (cid, owner),
            )
            row = await cur.fetchone()
            if row is None:
                yield None
                return
            # A session lock spans journal reservation, ONB, and final commit without an open transaction.
            cur = await conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 1354921809)) AS acquired", (cid,),
            )
            lock = await cur.fetchone()
            if not lock or not lock["acquired"]:
                raise ConversationBusy
            cur = await conn.execute(
                "SELECT view, dialogue FROM copilot_conversations WHERE id = %s AND merchant_id = %s",
                (cid, owner),
            )
            row = await cur.fetchone()
            yield ConversationHistory(conn, cid, row["view"], row["dialogue"]) if row else None


class ConversationBusy(Exception):
    pass


class ConversationHistory:
    def __init__(self, conn: AsyncConnection, cid: str, view: dict, dialogue: dict) -> None:
        self.conn = conn
        self.cid = cid
        self.view = view
        self.dialogue = dialogue

    async def turn(self, key: str | None = None) -> Turn | None:
        if key is None:
            cur = await self.conn.execute(
                "SELECT key, input, reply FROM copilot_turns WHERE conversation_id = %s AND reply IS NULL",
                (self.cid,),
            )
        else:
            cur = await self.conn.execute(
                "SELECT key, input, reply FROM copilot_turns WHERE conversation_id = %s AND key = %s",
                (self.cid, key),
            )
        row = await cur.fetchone()
        return Turn(row["key"], row["input"], row["reply"]) if row else None

    async def reserve(self, key: str, payload: dict) -> Turn:
        await self.conn.execute(
            "INSERT INTO copilot_turns (conversation_id, key, input) VALUES (%s, %s, %s)",
            (self.cid, key, Jsonb(payload)),
        )
        return Turn(key, payload, None)

    async def finish(self, turn: Turn, reply: dict, view: dict, dialogue: dict) -> None:
        async with self.conn.transaction():
            await self.conn.execute(
                "UPDATE copilot_turns SET reply = %s WHERE conversation_id = %s AND key = %s AND reply IS NULL",
                (Jsonb(reply), self.cid, turn.key),
            )
            await self.save(view, dialogue)

    async def save(self, view: dict, dialogue: dict) -> None:
        await self.conn.execute(
            "UPDATE copilot_conversations SET view = %s, dialogue = %s WHERE id = %s",
            (Jsonb(view), Jsonb(dialogue), self.cid),
        )

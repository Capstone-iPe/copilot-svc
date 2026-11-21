"""PostgreSQL history and a durable journal for turns that call ONB."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

log = logging.getLogger("copilot.telemetry")


class TraceDeliveryError(Exception):
    """A failed or unconfirmed submission; the message must be safe to log."""


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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS copilot_trace_outbox (
                    conversation_id text NOT NULL, turn_key text NOT NULL, revision smallint NOT NULL,
                    payload jsonb NOT NULL, destination text NOT NULL,
                    attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
                    delivered_at timestamptz, last_error text,
                    PRIMARY KEY (conversation_id, turn_key, revision),
                    FOREIGN KEY (conversation_id, turn_key) REFERENCES copilot_turns (conversation_id, key)
                )
                """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS copilot_trace_due
                ON copilot_trace_outbox (destination, next_attempt_at) WHERE delivered_at IS NULL
                """)

    async def export_trace(self, destination: str, send: Callable[[dict], Awaitable[None]]) -> bool:
        async with await self.connect() as conn, conn.transaction():
            # Lock only the immutable outbox revision, never the conversation or pending turn.
            cur = await conn.execute("""
                SELECT item.conversation_id, item.turn_key, item.revision, item.payload, item.attempts
                FROM copilot_trace_outbox item
                WHERE item.destination = %s AND item.delivered_at IS NULL AND item.next_attempt_at <= now()
                    AND NOT EXISTS (
                        SELECT 1 FROM copilot_trace_outbox prior
                        WHERE prior.conversation_id = item.conversation_id AND prior.turn_key = item.turn_key
                            AND prior.destination = item.destination AND prior.revision < item.revision
                            AND prior.delivered_at IS NULL
                    )
                ORDER BY item.next_attempt_at
                LIMIT 1 FOR UPDATE OF item SKIP LOCKED
                """, (destination,))
            row = await cur.fetchone()
            if row is None:
                return False
            key = (row["conversation_id"], row["turn_key"], row["revision"])
            try:
                await send(row["payload"])
            except TraceDeliveryError as exc:
                error = str(exc)
                attempts = row["attempts"] + 1
                log.warning("Langfuse export failed trace_id=%s attempt=%s (%s)",
                            row["payload"]["trace_id"], attempts, error)
                await conn.execute("""
                    UPDATE copilot_trace_outbox SET attempts = %s, last_error = %s,
                        next_attempt_at = clock_timestamp() + %s * interval '1 second'
                    WHERE conversation_id = %s AND turn_key = %s AND revision = %s
                    """, (attempts, error, min(300, 2 ** min(attempts, 9)), *key))
            else:
                await conn.execute("""
                    UPDATE copilot_trace_outbox SET delivered_at = clock_timestamp(), last_error = NULL
                    WHERE conversation_id = %s AND turn_key = %s AND revision = %s
                    """, key)
            return True

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
            yield ConversationHistory(conn, cid, row["view"], row["dialogue"], owner) if row else None


class ConversationBusy(Exception):
    pass


class ConversationHistory:
    def __init__(self, conn: AsyncConnection, cid: str, view: dict, dialogue: dict, owner: str) -> None:
        self.conn = conn
        self.cid = cid
        self.view = view
        self.dialogue = dialogue
        self.owner = owner

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

    async def queue_trace(self, turn: Turn, payload: dict) -> None:
        await self.conn.execute("""
            INSERT INTO copilot_trace_outbox (conversation_id, turn_key, revision, payload, destination)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """, (self.cid, turn.key, payload["revision"], Jsonb(payload), payload["destination"]))

    async def finish(self, turn: Turn, reply: dict, view: dict, dialogue: dict, *, trace: dict | None = None) -> None:
        async with self.conn.transaction():
            await self.conn.execute(
                "UPDATE copilot_turns SET reply = %s WHERE conversation_id = %s AND key = %s AND reply IS NULL",
                (Jsonb(reply), self.cid, turn.key),
            )
            await self.save(view, dialogue)
            if trace is not None:
                await self.queue_trace(turn, trace)

    async def save(self, view: dict, dialogue: dict) -> None:
        await self.conn.execute(
            "UPDATE copilot_conversations SET view = %s, dialogue = %s WHERE id = %s",
            (Jsonb(view), Jsonb(dialogue), self.cid),
        )

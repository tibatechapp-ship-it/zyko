"""SQLite-backed conversation memory (stdlib ``sqlite3``, zero deps).

Sessions survive restarts on every platform — including Termux, where the
data directory follows XDG conventions under the app-private home.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path

from zyko.core.messages import Message, ToolCall
from zyko.platform.paths import sessions_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    created REAL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS messages (
    session_id TEXT,
    idx INTEGER,
    role TEXT,
    content TEXT,
    meta TEXT,
    PRIMARY KEY (session_id, idx)
);
"""


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or sessions_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    def create_session(self, title: str | None = None) -> str:
        session = uuid.uuid4().hex[:12]
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, title, created, updated) VALUES (?, ?, ?, ?)",
                (session, title, now, now),
            )
            self._conn.commit()
        return session

    def append(self, session: str, message: Message) -> None:
        import json

        meta = None
        if message.tool_calls:
            meta = json.dumps(
                [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in message.tool_calls
                ],
                ensure_ascii=False,
            )
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(idx), -1) FROM messages WHERE session_id = ?", (session,)
            ).fetchone()
            idx = int(row[0]) + 1
            self._conn.execute(
                "INSERT INTO messages (session_id, idx, role, content, meta) VALUES (?, ?, ?, ?, ?)",
                (session, idx, message.role.value, message.content, meta),
            )
            self._conn.execute(
                "UPDATE sessions SET updated = ?, title = COALESCE(title, ?) WHERE id = ?",
                (time.time(), (message.content or "")[:60] or None, session),
            )
            self._conn.commit()

    def history(self, session: str, limit: int | None = None) -> list[Message]:
        import json

        query = "SELECT role, content, meta FROM messages WHERE session_id = ? ORDER BY idx"
        params: tuple = (session,)
        if limit:
            query += " DESC LIMIT ?"
            params = (session, limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        if limit:
            rows.reverse()
        messages: list[Message] = []
        for role, content, meta in rows:
            tool_calls = None
            if meta:
                try:
                    tool_calls = [
                        ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments") or {})
                        for tc in json.loads(meta)
                    ]
                except (json.JSONDecodeError, KeyError):
                    tool_calls = None
            messages.append(Message(role=role, content=content, tool_calls=tool_calls))
        return messages

    def delete_session(self, session: str) -> bool:
        """Remove a session and all of its messages. True if it existed."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session,)
            ).fetchone()
            existed = row is not None
            if existed:
                self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session,))
                self._conn.execute("DELETE FROM sessions WHERE id = ?", (session,))
                self._conn.commit()
        return existed

    def clear(self) -> int:
        """Delete every session and message. Returns the number of sessions removed."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
            count = int(row[0])
            if count:
                self._conn.execute("DELETE FROM messages")
                self._conn.execute("DELETE FROM sessions")
                self._conn.commit()
        return count

    def list_sessions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, s.title, s.created, s.updated, COUNT(m.idx) FROM sessions s "
                "LEFT JOIN messages m ON m.session_id = s.id GROUP BY s.id ORDER BY s.updated DESC"
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "created": r[2], "updated": r[3], "messages": r[4]}
            for r in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

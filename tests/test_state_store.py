from types import SimpleNamespace

import pytest

from veridex.config import Settings
from veridex.state.store import (
    FirestoreStore,
    MemoryStore,
    SqliteStore,
    create_store,
    make_turn,
    to_messages,
)


def turn(n: int) -> dict:
    return {"question": f"q{n}", "answer": f"a{n}", "citations": [], "routing": [], "created_at": n}


class FakeFirestore:
    """In-memory stand-in for the AsyncClient surface FirestoreStore uses."""

    def __init__(self):
        self.docs: dict[str, dict] = {}

    def collection(self, name):
        return FakeCollection(self, name)


class FakeCollection:
    def __init__(self, db, path, order=None, descending=False, limit=None):
        self.db, self.path, self.order, self.descending, self._limit = (
            db,
            path,
            order,
            descending,
            limit,
        )

    def document(self, doc_id=None):
        return FakeDocument(self.db, f"{self.path}/{doc_id or len(self.db.docs)}")

    async def add(self, data):
        await self.document(f"auto{len(self.db.docs)}").set(data)

    def order_by(self, field, direction):
        return FakeCollection(self.db, self.path, field, direction == "DESCENDING")

    def limit(self, n):
        return FakeCollection(self.db, self.path, self.order, self.descending, n)

    async def stream(self):
        prefix = self.path + "/"
        rows = [
            (path, data)
            for path, data in self.db.docs.items()
            if path.startswith(prefix) and "/" not in path[len(prefix) :]
        ]
        if self.order:
            rows.sort(key=lambda row: row[1][self.order], reverse=self.descending)
        for path, data in rows[: self._limit]:
            yield SimpleNamespace(
                to_dict=lambda data=data: dict(data), reference=FakeDocument(self.db, path)
            )


class FakeDocument:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def collection(self, name):
        return FakeCollection(self.db, f"{self.path}/{name}")

    async def set(self, data, merge=False):
        current = self.db.docs.get(self.path, {}) if merge else {}
        self.db.docs[self.path] = {**current, **data}

    async def delete(self):
        self.db.docs.pop(self.path, None)


@pytest.fixture(params=["memory", "sqlite", "firestore"])
def store(request, tmp_path):
    if request.param == "memory":
        return MemoryStore()
    if request.param == "sqlite":
        return SqliteStore(tmp_path / "state" / "conversations.db")
    return FirestoreStore(FakeFirestore(), "veridex_conversations")


@pytest.mark.asyncio
async def test_store_keeps_latest_turns_in_order_per_session(store):
    for n in range(1, 6):
        await store.append("a", turn(n))
    await store.append("b", turn(99))
    assert [t["question"] for t in await store.load("a", 3)] == ["q3", "q4", "q5"]
    assert [t["question"] for t in await store.load("b", 3)] == ["q99"]
    assert await store.load("missing", 3) == []
    await store.delete("a")
    assert await store.load("a", 3) == []
    assert len(await store.load("b", 3)) == 1


@pytest.mark.asyncio
async def test_sqlite_state_survives_a_new_store_instance(tmp_path):
    path = tmp_path / "conversations.db"
    await SqliteStore(path).append("s", turn(1))
    assert await SqliteStore(path).load("s", 5) == [turn(1)]


def test_turn_record_and_replayed_messages():
    output = {
        "response": "answer",
        "citations": [{"id": "react_2022:p2:c012", "title": "ReAct"}],
        "routing": [
            {
                "agent": "research",
                "provider": "gemini",
                "model": "m",
                "rule": "single_lookup",
                "fallback_from": None,
                "signals": {"x": 1},
            }
        ],
    }
    record = make_turn("question", output)
    assert record["citations"] == ["react_2022:p2:c012"]
    assert "signals" not in record["routing"][0]
    assert [(m.type, m.content) for m in to_messages([record])] == [
        ("human", "question"),
        ("ai", "answer"),
    ]


def test_create_store_selects_backend(tmp_path):
    memory = create_store(Settings(_env_file=None, state_backend="memory"))
    assert memory.backend == "memory"
    sqlite = create_store(
        Settings(_env_file=None, state_backend="sqlite", state_sqlite_path=tmp_path / "s.db")
    )
    assert sqlite.backend == "sqlite" and (tmp_path / "s.db").exists()

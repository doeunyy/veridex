"""Request-local execution budgets and public-API in-memory checkpoint compaction."""

from dataclasses import dataclass
from itertools import groupby


class AgentBudgetExceeded(RuntimeError):
    """A turn reached a configured local execution limit."""


class SessionCapacityError(RuntimeError):
    """All retained session slots are occupied; no conversation was evicted."""


@dataclass
class TurnBudget:
    max_tools: int
    max_models: int
    max_characters: int
    tools: int = 0
    models: int = 0

    def before_tools(self, messages):
        count = len(messages[-1].tool_calls)
        if self.tools + count > self.max_tools:
            raise AgentBudgetExceeded("tool_call_limit")
        self.tools += count

    def before_model(self, messages):
        # Conservative serialized-character bound, not an exact tokenizer/cost estimate.
        if sum(len(message.model_dump_json()) for message in messages) > self.max_characters:
            raise AgentBudgetExceeded("context_limit")
        if self.models >= self.max_models:
            raise AgentBudgetExceeded("model_call_limit")
        self.models += 1


async def compact_memory(saver, session_id, turns):
    """Keep complete recent human turns and one checkpoint, including pending writes.

    Called only while the session lock is owned, after a turn/repair. No checkpoint
    internals are edited. Other session namespaces and the saver instance are retained.
    """
    config = {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}
    latest = await saver.aget_tuple(config)
    if latest is None:
        return
    checkpoint = latest.checkpoint.copy()
    values = checkpoint["channel_values"].copy()
    messages = values.get("messages", [])
    boundaries = [index for index, message in enumerate(messages) if message.type == "human"]
    if len(boundaries) > turns:
        values["messages"] = messages[boundaries[-turns] :]
    checkpoint["channel_values"] = values
    # These public InMemorySaver methods complete without yielding; deletion/re-save
    # is atomic with respect to other asyncio tasks in this process.
    await saver.adelete_thread(session_id)
    saved = await saver.aput(config, checkpoint, latest.metadata, checkpoint["channel_versions"])
    for task, writes in groupby(
        sorted(latest.pending_writes, key=lambda row: row[0]), lambda r: r[0]
    ):
        await saver.aput_writes(saved, [(channel, value) for _, channel, value in writes], task)

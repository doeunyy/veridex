"""LangGraph state for the supervisor graph.

`messages` is the conversation and persists across turns. Every other list is per
turn: the service resets it by sending None at the start of a turn.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.config import get_stream_writer
from langgraph.graph.message import add_messages

WorkerName = Literal["research", "summary", "data"]
Next = Literal["research", "summary", "data", "finish"]
WORKERS: tuple[WorkerName, ...] = ("research", "summary", "data")


def announce(kind: str, data: dict) -> None:
    """Push a live event to graph.astream(stream_mode="custom"); a no-op outside a run."""
    try:
        get_stream_writer()({"kind": kind, "data": data})
    except RuntimeError:
        pass


def per_turn(left: list | None, right: list | None) -> list:
    """Append within a turn; None starts a new turn."""
    if right is None:
        return []
    return [*(left or []), *right]


class SupervisorState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    question: str  # the current user turn
    next: Next  # supervisor's latest choice
    task: str  # instruction for the chosen worker
    reason: str  # why the supervisor chose it
    direct_answer: str  # supervisor answer when no worker is needed
    hops: int  # workers dispatched this turn
    results: Annotated[list[dict], per_turn]  # one WorkerResult per worker run
    routing: Annotated[list[dict], per_turn]  # every RoutingDecision, in order
    trace: Annotated[list[dict], per_turn]  # orchestration events, in order
    answer: str  # final answer for this turn
    citations: list[dict]  # sources cited in the final answer

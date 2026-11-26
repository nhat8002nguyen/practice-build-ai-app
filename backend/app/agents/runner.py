from dataclasses import dataclass, field
from functools import lru_cache

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph, initial_state
from app.agents.tools import ToolContext
from app.services.llm import LLM


@lru_cache
def get_checkpointer() -> BaseCheckpointSaver:
    # In-process: a paused run is lost on restart or on another worker. resume_agent returns
    # None then and resolve fails with 409 (ticket stays open). Use a Postgres saver to survive.
    return MemorySaver()


@dataclass
class AgentResult:
    answer: str
    citations: list[dict[str, str]] = field(default_factory=list)
    ticket_id: str | None = None
    awaiting_human: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def run_agent(
    ctx: ToolContext, llm: LLM, question: str, history: list[dict[str, str]]
) -> AgentResult:
    graph = build_graph(ctx, llm, get_checkpointer())
    state = await graph.ainvoke(initial_state(question, history), _config(ctx.thread_id))
    return AgentResult(
        answer=state["answer"],
        citations=state["citations"],
        ticket_id=state["ticket_id"],
        awaiting_human="__interrupt__" in state,
        prompt_tokens=state["prompt_tokens"],
        completion_tokens=state["completion_tokens"],
    )


async def resume_agent(
    ctx: ToolContext, llm: LLM, decision: str, note: str | None
) -> str | None:
    """Finish a paused run with the human decision. None if no paused run exists."""
    graph = build_graph(ctx, llm, get_checkpointer())
    config = _config(ctx.thread_id)
    if not (await graph.aget_state(config)).next:
        return None
    state = await graph.ainvoke(
        Command(resume={"decision": decision, "note": note}), config
    )
    return state["answer"]

import json
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.tools import (
    TOOL_DESCRIPTIONS,
    ToolContext,
    ToolError,
    run_tool,
    search_knowledge,
)
from app.services.llm import LLM

MAX_ASSISTANT_STEPS = 6
FALLBACK_ANSWER = "I could not complete this request. Please contact support."
HITL_PLACEHOLDER = "Your request has been escalated for human review."

SYSTEM_PROMPT = f"""You are a support agent for a small business. Decide one step at a time.
Reply with a JSON object, either a tool call:
{{"action": "tool", "tool": "<name>", "args": {{...}}}}
or the final reply to the customer:
{{"action": "final", "answer": "<text>"}}

{TOOL_DESCRIPTIONS}

Policy:
- Use search_knowledge for policy and product questions. Never invent policy.
- Use lookup_order when the customer mentions an order id.
- If an order is not found, or the knowledge base has no grounded answer, call create_ticket,
  then tell the customer a human will follow up.
"""


class AgentState(TypedDict):
    question: str
    history: list[dict[str, str]]
    scratch: list[dict[str, str]]  # model <-> tool turns of this run
    pending: dict[str, Any] | None  # tool call requested by the assistant node
    steps: int
    answer: str
    citations: list[dict[str, str]]
    ticket_id: str | None
    decision: str | None
    note: str | None
    prompt_tokens: int
    completion_tokens: int
    grounded_answer: str | None
    order_status: dict[str, Any] | None
    refused: bool


def format_order_status(order: dict[str, Any]) -> str:
    return (
        f"Order {order['order_id']} is {order['status']} "
        f"via {order['carrier']}, ETA {order['eta_days']} days."
    )


def initial_state(question: str, history: list[dict[str, str]]) -> AgentState:
    return AgentState(
        question=question,
        history=history,
        scratch=[],
        pending=None,
        steps=0,
        answer="",
        citations=[],
        ticket_id=None,
        decision=None,
        note=None,
        prompt_tokens=0,
        completion_tokens=0,
        grounded_answer=None,
        order_status=None,
        refused=False,
    )


def resolution_message(decision: str, note: str | None) -> str:
    outcome = (
        "A human agent reviewed your request and approved it."
        if decision == "approve"
        else "A human agent reviewed your request and could not approve it."
    )
    return f"{outcome} {note}".strip() if note else outcome


def _parse_action(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"action": "final", "answer": FALLBACK_ANSWER}
    return parsed if isinstance(parsed, dict) else {"action": "final", "answer": FALLBACK_ANSWER}


def _apply_search_citations(
    prior: list[dict[str, str]], answers: list[Any]
) -> list[dict[str, str]]:
    """Latest search wins: replace with that answer's citations, or clear on refuse."""
    if not answers:
        return list(prior)
    citations: dict[str, dict[str, str]] = {}
    for answer in answers:
        if answer.refused:
            citations = {}
        else:
            citations = {c.chunk_id: vars(c) for c in answer.citations}
    return list(citations.values())


def _compose_order_and_grounded(state: AgentState) -> dict[str, Any] | None:
    """Lead with order status when found; append non-refused grounded policy when both exist."""
    order = state["order_status"]
    grounded = state["grounded_answer"]
    has_policy = grounded is not None and not state["refused"]
    if order is not None and has_policy:
        return {
            "answer": f"{format_order_status(order)}\n\n{grounded}",
            "refused": False,
        }
    if has_policy:
        return {"answer": grounded, "refused": False}
    if order is not None:
        return {
            "answer": format_order_status(order),
            "refused": False,
            "citations": [],
        }
    if grounded is not None:
        return {
            "answer": grounded,
            "refused": True,
            "citations": [],
        }
    return None


def build_graph(ctx: ToolContext, llm: LLM, checkpointer: BaseCheckpointSaver):
    """assistant -> tools -> assistant -> (hitl) -> finalize, one compiled graph per request."""

    async def _ground_with_search(state: AgentState, usage: dict[str, Any]) -> dict[str, Any]:
        await search_knowledge(ctx, state["question"])
        answer = ctx.take_search_answers()[-1]
        return {
            **usage,
            "pending": None,
            "answer": answer.text,
            "refused": answer.refused,
            "citations": _apply_search_citations(state["citations"], [answer]),
            "grounded_answer": answer.text,
            "prompt_tokens": usage["prompt_tokens"] + answer.usage.prompt_tokens,
            "completion_tokens": usage["completion_tokens"] + answer.usage.completion_tokens,
        }

    # NODE assistant: the model picks the next step, either a tool call or the final reply.
    async def assistant(state: AgentState) -> dict[str, Any]:
        messages = [
            *state["history"],
            {"role": "user", "content": state["question"]},
            *state["scratch"],
        ]
        result = await llm.complete(SYSTEM_PROMPT, messages)
        usage = {
            "steps": state["steps"] + 1,
            "prompt_tokens": state["prompt_tokens"] + result.prompt_tokens,
            "completion_tokens": state["completion_tokens"] + result.completion_tokens,
        }
        action = _parse_action(result.text)
        if action.get("action") == "tool" and state["steps"] + 1 < MAX_ASSISTANT_STEPS:
            call = {"tool": action.get("tool"), "args": action.get("args") or {}}
            scratch = [*state["scratch"], {"role": "assistant", "content": result.text}]
            return {**usage, "pending": call, "scratch": scratch}

        # Budget-exhausted tool actions fall through the same cascade as finals.
        if action.get("action") == "tool":
            answer = FALLBACK_ANSWER
        else:
            answer = str(action.get("answer") or "").strip() or FALLBACK_ANSWER
        composed = _compose_order_and_grounded(state)
        # HITL draft: never free-form model text; safe tool outcomes or placeholder.
        if state["ticket_id"]:
            if composed is not None and not composed.get("refused", False):
                return {**usage, "pending": None, **composed}
            return {
                **usage,
                "pending": None,
                "answer": HITL_PLACEHOLDER,
                "citations": [],
            }
        if composed is not None:
            return {**usage, "pending": None, **composed}
        # Non-policy safe fallback (parse failure / explicit fallback text / budget).
        if answer == FALLBACK_ANSWER:
            return {
                **usage,
                "pending": None,
                "answer": FALLBACK_ANSWER,
                "citations": [],
            }
        # No grounding yet: same retrieve + citation/refusal path as RAG mode.
        return await _ground_with_search(state, usage)

    # NODE tools: run the requested tool and feed the observation back to the model.
    async def tools(state: AgentState) -> dict[str, Any]:
        call = state["pending"] or {}
        tool_name = str(call.get("tool") or "")
        ticket_id = state["ticket_id"]
        order_status = state["order_status"]
        try:
            output = await run_tool(ctx, tool_name, call.get("args"))
        except ToolError as error:
            observation = f"error: {error}"
        else:
            observation = output if isinstance(output, str) else json.dumps(output)
            if tool_name == "create_ticket":
                ticket_id = output
            if tool_name == "lookup_order" and isinstance(output, dict):
                order_status = output if output.get("found") else None

        prompt_tokens, completion_tokens = state["prompt_tokens"], state["completion_tokens"]
        grounded_answer = state["grounded_answer"]
        refused = state["refused"]
        search_answers = ctx.take_search_answers()
        for answer in search_answers:
            prompt_tokens += answer.usage.prompt_tokens
            completion_tokens += answer.usage.completion_tokens
            grounded_answer = answer.text
            refused = answer.refused
        citations = _apply_search_citations(state["citations"], search_answers)
        scratch = [
            *state["scratch"],
            {"role": "user", "content": f"Tool result: {observation}"},
        ]
        return {
            "scratch": scratch,
            "pending": None,
            "ticket_id": ticket_id,
            "citations": citations,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "grounded_answer": grounded_answer,
            "order_status": order_status,
            "refused": refused,
        }

    # NODE hitl: pause the run until a human resolves the ticket via the API.
    # interrupt() checkpoints state and returns the resume payload on re-entry.
    # This node re-runs from the top on resume, so it must stay side-effect free.
    def hitl(state: AgentState) -> dict[str, Any]:
        decision = interrupt({"ticket_id": state["ticket_id"]})
        return {"decision": decision["decision"], "note": decision.get("note")}

    # NODE finalize: after a human decision the reply is the decision, not the draft.
    def finalize(state: AgentState) -> dict[str, Any]:
        if state["decision"]:
            return {
                "answer": resolution_message(state["decision"], state["note"]),
                "refused": False,
                "citations": [],
            }
        return {}

    def after_assistant(state: AgentState) -> str:
        if state["pending"]:
            return "tools"
        return "hitl" if state["ticket_id"] else "finalize"

    graph = StateGraph(AgentState)
    graph.add_node("assistant", assistant)
    graph.add_node("tools", tools)
    graph.add_node("hitl", hitl)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "assistant")
    graph.add_conditional_edges(
        "assistant", after_assistant, ["tools", "hitl", "finalize"]
    )
    graph.add_edge("tools", "assistant")
    graph.add_edge("hitl", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)

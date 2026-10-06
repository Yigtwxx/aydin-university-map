"""A deterministic, offline stand-in for the LLM (unit tests and browser E2E).

Selected with ``AMAP_ASSISTANT_MODEL=offline``: asked about a block ("E
Blok"), it calls ``get_route`` to that block's entrance and then summarises;
otherwise it greets. No network, no API keys.
"""

import json
import re
from collections.abc import AsyncIterator

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)

_BLOCK = re.compile(r"\b([A-Za-z])\s*blo(?:k|ck)\b", re.IGNORECASE)


def _last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    return ""


def _after_tool(messages: list[ModelMessage]) -> ToolReturnPart | None:
    last = messages[-1] if messages else None
    if isinstance(last, ModelRequest):
        for part in last.parts:
            if isinstance(part, ToolReturnPart):
                return part
    return None


def _reply(messages: list[ModelMessage]) -> str | tuple[str, dict[str, str]]:
    returned = _after_tool(messages)
    if returned is not None:
        content = returned.content if isinstance(returned.content, dict) else {}
        if "error" in content:
            return "Bu iki yer arasında henüz bir rota bulamadım."
        minutes = content.get("duration_min", 1)
        metres = content.get("length_m", 0)
        return f"Rotayı haritaya çizdim: yaklaşık {minutes} dakika, {metres} metre."
    match = _BLOCK.search(_last_user_text(messages))
    if match:
        return ("get_route", {"to_place": f"{match.group(1).upper()} Blok"})
    return "Merhaba! Kampüste nereye gitmek istersiniz?"


def offline_model() -> FunctionModel:
    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        reply = _reply(messages)
        if isinstance(reply, tuple):
            name, args = reply
            return ModelResponse(parts=[ToolCallPart(name, args)])
        return ModelResponse(parts=[TextPart(reply)])

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        reply = _reply(messages)
        if isinstance(reply, tuple):
            name, args = reply
            yield {0: DeltaToolCall(name=name, json_args=json.dumps(args))}
            return
        for word in reply.split(" "):
            yield word + " "

    return FunctionModel(respond, stream_function=stream, model_name="offline")

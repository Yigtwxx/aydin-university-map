"""Campus assistant with the offline model (no network, no API keys)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from amap_api.assistant.agent import keep_recent
from amap_api.graph_store import GraphStore
from amap_api.main import CHAT_BUCKET, create_app
from amap_api.rate_limit import TokenBucket
from amap_api.settings import Settings


@pytest.fixture
def chat_client(store: GraphStore) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        graph_source="unused",
        amap_assistant_model="offline",
    )
    CHAT_BUCKET._tokens.clear()  # pyright: ignore[reportPrivateUsage]
    with TestClient(create_app(settings=settings, store=store)) as client:
        yield client


def _ask(text: str) -> dict[str, object]:
    return {
        "trigger": "submit-message",
        "id": "chat-1",
        "messages": [
            {"id": "m1", "role": "user", "parts": [{"type": "text", "text": text}]}
        ],
    }


def test_chat_streams_route_tool_call_and_answer(chat_client: TestClient) -> None:
    response = chat_client.post("/chat", json=_ask("A blok nerede?"))
    body = response.text
    assert response.status_code == 200, body
    assert '"toolName":"get_route"' in body, "route tool call must stream"
    assert '"node_ids":["a","b","c"]' in body, "tool output carries the route"
    assert '"delta":"Rotayı ' in body, "final answer streams word by word"


def test_chat_rejects_long_questions(chat_client: TestClient) -> None:
    response = chat_client.post("/chat", json=_ask("x" * 1001))
    assert response.status_code == 413, response.text


def test_chat_without_models_is_unavailable(client: TestClient) -> None:
    assert client.post("/chat", json=_ask("merhaba")).status_code == 503


def test_token_bucket_blocks_bursts_then_refills() -> None:
    bucket = TokenBucket(capacity=2, refill_per_s=1.0)
    assert bucket.allow("ip", now=0.0) and bucket.allow("ip", now=0.0)
    assert not bucket.allow("ip", now=0.0), "third request in a burst is blocked"
    assert bucket.allow("ip", now=1.0), "one token is back after a second"


def test_keep_recent_starts_at_a_user_turn() -> None:
    def turn(i: int) -> list[object]:
        return [
            ModelRequest(parts=[UserPromptPart(content=f"q{i}")]),
            ModelResponse(parts=[ToolCallPart("get_route", {"to_place": "x"})]),
            ModelRequest(parts=[ToolReturnPart("get_route", {}, tool_call_id="t")]),
            ModelResponse(parts=[TextPart(f"a{i}")]),
        ]

    history = [m for i in range(4) for m in turn(i)]
    kept = keep_recent(history)  # pyright: ignore[reportArgumentType]
    first = kept[0]
    assert isinstance(first, ModelRequest), "history must start with a request"
    assert isinstance(first.parts[0], UserPromptPart), "...that is a user prompt"
    assert len(kept) <= 8, f"kept {len(kept)} messages"

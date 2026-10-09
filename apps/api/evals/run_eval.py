"""Evaluate the campus assistant against a frozen question set (Step 4.4).

Every question in ``questions.yaml`` goes through the real agent, built the
way the API builds it (``build_model`` + ``build_agent``, deps over the
walking graph, its places and the pgvector knowledge base). The run records
the tool calls and their outputs (pydantic-ai message history), the retrieved
chunks and the final answer, then scores:

- **correct tool**: the tools called match the question's expectation;
- **context recall**: share of the expected facts that occur in what the
  tools returned (what the model actually saw);
- **faithfulness**: share of the answer's claims supported by the tool
  outputs, judged by Gemini Flash-Lite with a strict rubric (``judge_v2.md``;
  ``judge_v1.md`` is kept for the first baseline). Web addresses and phone
  numbers are also checked character for character.

Reported for information: language match, ``answered`` (the reply responds
to the question at all), ``abstention`` (says "I don't know" exactly when
the question expects it), ``target_place`` (route endpoints / place found),
``judged`` (share of questions with a faithfulness score) and the p95 answer
latency without pacing waits.

Usage, from the repository root::

    uv run python apps/api/evals/run_eval.py               # full run
    uv run python apps/api/evals/run_eval.py --only tr-route-01 en-know-02
    uv run python apps/api/evals/run_eval.py --validate    # check the set only
    uv run python apps/api/evals/run_eval.py --rejudge apps/api/evals/results/X.json

Groq's free tier allows 8K tokens a minute, so model requests are paced (one
every 3 s at most, about 7K tokens a minute) and rate-limit or server errors
are retried with backoff. A full run takes 15-25 minutes. When a free-tier
daily quota is spent (Gemini: 1,000 embeddings, 500 Flash-Lite calls) the run
stops at once, keeps the finished answers and exits with code 2. Keys and
database URLs come from the repo-root ``.env`` and are never printed.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import Counter, deque
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    ModelHTTPError,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from amap_api.assistant import agent as assistant
from amap_api.assistant.knowledge import Knowledge
from amap_api.db import Database
from amap_api.graph_store import GraphStore, load_graph, load_pois
from amap_api.places import Place, build_places
from amap_api.settings import Settings
from amap_contracts.text import lower_tr

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parents[2]
QUESTIONS_FILE = EVAL_DIR / "questions.yaml"
JUDGE_PROMPT = "judge_v2.md"
PROMPTS_DIR = assistant.PROMPT_PATH.parent
RESULTS_DIR = EVAL_DIR / "results"

JUDGE_MODEL = "gemini-3.5-flash-lite"
TARGETS = {"correct_tool": 0.90, "context_recall": 0.80, "faithfulness": 0.85}
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_JUDGE_CONTEXT_CHARS = 14_000

ToolName = Literal["search_places", "get_route", "search_knowledge", "describe_place"]
Lang = Literal["tr", "en"]


# --- question set -----------------------------------------------------------


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[ToolName] = Field(default_factory=list)
    one_of: list[ToolName] = Field(default_factory=list)
    allowed: list[ToolName] = Field(default_factory=list)


class RouteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    start: str = Field(alias="from")
    to: str
    avoid_stairs: bool | None = None


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    lang: Lang
    category: Literal["route", "place", "knowledge", "out_of_scope", "chitchat"]
    question: str
    tools: ToolSpec
    route: RouteSpec | None = None
    # Any of these place ids (several rooms can share a name).
    place: str | list[str] | None = None

    @property
    def place_ids(self) -> list[str]:
        if self.place is None:
            return []
        return [self.place] if isinstance(self.place, str) else list(self.place)

    facts: list[str | list[str]] = Field(default_factory=list)
    abstain: bool = False


class QuestionSet(BaseModel):
    version: int
    questions: list[Question]


def load_questions(path: Path) -> list[Question]:
    data = QuestionSet.model_validate(yaml.safe_load(path.read_text("utf-8")))
    ids = [q.id for q in data.questions]
    duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
    if duplicates:
        raise SystemExit(f"duplicate question ids: {', '.join(duplicates)}")
    return data.questions


# --- fact matching ----------------------------------------------------------

_TO_ASCII = str.maketrans(
    {"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i"}
    # Route steps write basements with U+2212 ("\u22121. kat"), the knowledge
    # base with "-": both are the same minus sign here.
    | {"\u2212": "-"}
)
# Keeps "-": "-3. kat" (a basement) must not match "3. kat".
_NON_TOKEN = re.compile(r"[^0-9a-z-]+")


def normalize(text: str) -> str:
    """Turkish-aware, accent-free, space-separated tokens (minus signs kept)."""
    folded = lower_tr(text).translate(_TO_ASCII)
    decomposed = unicodedata.normalize("NFKD", folded)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(_NON_TOKEN.sub(" ", plain).split())


def fact_alternatives(fact: str | list[str]) -> list[str]:
    return [fact] if isinstance(fact, str) else list(fact)


def fact_label(fact: str | list[str]) -> str:
    return " | ".join(fact_alternatives(fact))


def contains_fact(haystack: str, fact: str | list[str]) -> bool:
    """``haystack`` must already be normalized; matches whole tokens only."""
    padded = f" {haystack} "
    return any(f" {normalize(alt)} " in padded for alt in fact_alternatives(fact))


def strings_in(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from strings_in(item)


# --- pacing and retries -----------------------------------------------------


def log(message: str) -> None:
    print(message, flush=True)


@dataclass(slots=True)
class Pacer:
    """At most one request every ``min_interval_s`` and ``tokens_per_minute``."""

    min_interval_s: float
    tokens_per_minute: int = 1_000_000
    estimate: int = 3_000
    waited: float = 0.0  # seconds spent pacing or backing off, not working
    _last_start: float = 0.0
    _window: deque[tuple[float, int]] = field(default_factory=deque)

    def _used(self, now: float) -> int:
        while self._window and now - self._window[0][0] >= 60.0:
            self._window.popleft()
        return sum(tokens for _, tokens in self._window)

    async def wait(self) -> None:
        while True:
            now = time.monotonic()
            delay = self._last_start + self.min_interval_s - now
            if self._window and (
                self._used(now) + self.estimate > self.tokens_per_minute
            ):
                delay = max(delay, self._window[0][0] + 60.0 - now)
            if delay <= 0:
                break
            await self.sleep(delay)
        self._last_start = time.monotonic()

    async def sleep(self, seconds: float) -> None:
        self.waited += seconds
        await asyncio.sleep(seconds)

    def record(self, tokens: int) -> None:
        self._window.append((time.monotonic(), tokens))
        self.estimate = max(1_500, tokens)


def _leaf_errors(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for sub in exc.exceptions for leaf in _leaf_errors(sub)]
    return [exc]


class QuotaExhaustedError(RuntimeError):
    """A free-tier daily quota is spent: retrying now cannot help."""


# A provider asking to wait longer than this has hit a daily, not a per-minute,
# limit (Gemini free tier: 1,000 embeddings and 500 Flash-Lite calls a day).
MAX_RETRY_WAIT_S = 600.0
_GEMINI_RETRY = re.compile(r"retryDelay'?\s*:\s*'(\d+(?:\.\d+)?)s'")


def _retry_hint(leaf: BaseException) -> float:
    """Seconds the provider asks to wait (a daily quota counts as forever)."""
    if isinstance(leaf, ModelHTTPError):
        # Gemini inside the FallbackModel: the hint is in the body, not a header.
        detail = str(leaf.body)
        hint = leaf.retry_after
    elif isinstance(leaf, genai_errors.APIError):
        detail = str(leaf)
        hint = None
    else:
        return 0.0
    if "PerDay" in detail:  # quotaId "...RequestsPerDayPerUser...": wait is moot
        return math.inf
    if hint is None:
        match = _GEMINI_RETRY.search(detail)
        hint = float(match.group(1)) if match else 0.0
    return hint


def backoff_delay(exc: BaseException, attempt: int) -> float | None:
    """Seconds to wait before retrying ``exc``, or None if it is not transient.

    Raises QuotaExhaustedError when the provider asks to wait for hours.
    """
    hints: list[float] = []  # one per transient failure (one per fallback model)
    for leaf in _leaf_errors(exc):
        if isinstance(leaf, ModelHTTPError):
            transient = leaf.status_code in RETRYABLE_STATUS
        elif isinstance(leaf, genai_errors.APIError):
            transient = leaf.code in RETRYABLE_STATUS
        else:
            transient = isinstance(leaf, ModelAPIError)  # connection, timeout
        if transient:
            hints.append(_retry_hint(leaf))
    if not hints:
        return None
    # The chain works again as soon as its first model does.
    hinted = min(hints)
    if hinted > MAX_RETRY_WAIT_S:
        wait = "later" if math.isinf(hinted) else f"in {hinted / 3600:.1f} h"
        raise QuotaExhaustedError(f"{_short(exc)}: daily quota spent, retry {wait}")
    # Honour the provider's hint (at most MAX_RETRY_WAIT_S), else back off.
    return max(hinted, min(120.0, 10.0 * 2**attempt))


class PacedModel(WrapperModel):
    """Paces and retries requests to the API's model chain (FallbackModel)."""

    def __init__(self, wrapped: Model, pacer: Pacer, max_attempts: int = 5) -> None:
        super().__init__(wrapped)
        self.pacer = pacer
        self.max_attempts = max_attempts

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        attempt = 0
        while True:
            await self.pacer.wait()
            try:
                response = await self.wrapped.request(
                    messages, model_settings, model_request_parameters
                )
            except (ModelAPIError, FallbackExceptionGroup) as exc:
                delay = backoff_delay(exc, attempt)
                attempt += 1
                if delay is None or attempt >= self.max_attempts:
                    raise
                log(f"    every model failed ({_short(exc)}); retry in {delay:.0f}s")
                await self.pacer.sleep(delay)
                continue
            self.pacer.record(response.usage.total_tokens)
            return response


def _short(exc: BaseException) -> str:
    """Error kinds and status codes only: provider bodies stay out of the logs."""
    parts: list[str] = []
    for leaf in _leaf_errors(exc):
        if isinstance(leaf, ModelHTTPError):
            parts.append(f"{leaf.model_name}: HTTP {leaf.status_code}")
        elif isinstance(leaf, genai_errors.APIError):
            parts.append(f"gemini: HTTP {leaf.code}")
        else:
            parts.append(type(leaf).__name__)
    return ", ".join(parts)


# --- running the agent ------------------------------------------------------


@dataclass(slots=True)
class ToolTrace:
    name: str
    args: dict[str, Any]
    output: Any  # the tool's return value (None if it never returned)
    text: str  # the return value as the model saw it


@dataclass(slots=True)
class RunTrace:
    answer: str
    tools: list[ToolTrace]
    models: list[str]
    input_tokens: int
    output_tokens: int
    requests: int
    seconds: float
    attempts: int
    error: str | None = None
    active_seconds: float = 0.0  # ``seconds`` minus pacing and backoff waits


def trace_tools(messages: Sequence[ModelMessage]) -> tuple[list[ToolTrace], list[str]]:
    """Tool calls in order, each with its return (or retry prompt), and models."""
    calls: list[ToolCallPart] = []
    returns: dict[str, tuple[Any, str]] = {}
    models: list[str] = []
    for message in messages:
        if isinstance(message, ModelResponse):
            models.append(message.model_name or "?")
            calls += [p for p in message.parts if isinstance(p, ToolCallPart)]
        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    returns[part.tool_call_id] = (
                        part.content,
                        part.model_response_str(),
                    )
                elif isinstance(part, RetryPromptPart) and part.tool_name:
                    text = part.model_response()
                    returns[part.tool_call_id] = ({"retry": text}, text)
    traces = [
        ToolTrace(
            name=call.tool_name,
            args=call.args_as_dict(),
            output=returns.get(call.tool_call_id, (None, ""))[0],
            text=returns.get(call.tool_call_id, (None, ""))[1],
        )
        for call in calls
    ]
    return traces, models


async def run_question(
    agent: Any,
    deps: assistant.AssistantDeps,
    question: Question,
    max_attempts: int,
    pacer: Pacer,
) -> RunTrace:
    attempt = 0
    while True:
        attempt += 1
        started = time.monotonic()
        waited = pacer.waited
        try:
            result = await agent.run(
                question.question, deps=deps, usage_limits=assistant.USAGE_LIMITS
            )
        except UsageLimitExceeded as exc:
            return RunTrace("", [], [], 0, 0, 0, 0.0, attempt, f"usage limit: {exc}")
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            delay = backoff_delay(exc, attempt - 1)  # may raise QuotaExhaustedError
            if delay is None or attempt >= max_attempts:
                return RunTrace(
                    "", [], [], 0, 0, 0, 0.0, attempt, f"{type(exc).__name__}"
                )
            log(f"    run failed ({_short(exc)}); retry in {delay:.0f}s")
            await asyncio.sleep(delay)
            continue
        tools, models = trace_tools(result.all_messages())
        usage = result.usage
        seconds = time.monotonic() - started
        return RunTrace(
            answer=str(result.output),
            tools=tools,
            models=models,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            requests=usage.requests,
            seconds=round(seconds, 1),
            attempts=attempt,
            active_seconds=round(seconds - (pacer.waited - waited), 1),
        )


# --- judge ------------------------------------------------------------------


class Claim(BaseModel):
    text: str
    supported: bool
    evidence: str


class Verdict(BaseModel):
    claims: list[Claim]
    answer_language: Literal["tr", "en", "mixed"]
    addresses_question: bool
    abstains: bool
    notes: str


def judge_input(question: Question, trace: RunTrace, instructions: str) -> str:
    context = "\n\n".join(
        f"[{i}] {t.name}({json.dumps(t.args, ensure_ascii=False)}) returned:\n{t.text}"
        for i, t in enumerate(trace.tools, 1)
    )
    if len(context) > MAX_JUDGE_CONTEXT_CHARS:
        log(f"    judge context cut at {MAX_JUDGE_CONTEXT_CHARS} of {len(context)}")
        context = context[:MAX_JUDGE_CONTEXT_CHARS] + "\n[context truncated]"
    return (
        f"QUESTION_LANGUAGE: {question.lang}\n"
        f"QUESTION: {question.question}\n\n"
        f"ASSISTANT_INSTRUCTIONS:\n{instructions}\n\n"
        f"CONTEXT:\n{context or '(empty: no tool was called)'}\n\n"
        f"ANSWER:\n{trace.answer}\n"
    )


@dataclass(slots=True)
class Judge:
    client: genai.Client
    model: str
    rubric: str
    pacer: Pacer
    max_attempts: int = 5

    async def __call__(self, contents: str) -> Verdict:
        config = genai_types.GenerateContentConfig(
            system_instruction=self.rubric,
            response_mime_type="application/json",
            response_schema=Verdict,
            temperature=0.0,
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        attempt = 0
        while True:
            await self.pacer.wait()
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                parsed = response.parsed
                if isinstance(parsed, Verdict):
                    return parsed
                return Verdict.model_validate_json(response.text or "")
            except (genai_errors.APIError, ValidationError) as exc:
                attempt += 1
                if isinstance(exc, ValidationError):
                    delay: float | None = 5.0
                else:
                    delay = backoff_delay(exc, attempt - 1)  # may raise
                if delay is None or attempt >= self.max_attempts:
                    raise
                log(f"    judge failed ({type(exc).__name__}); retry in {delay:.0f}s")
                await asyncio.sleep(delay)


# --- scoring ----------------------------------------------------------------


@dataclass(slots=True)
class Score:
    called: list[str]
    tool_ok: bool
    target_ok: bool | None  # route endpoints / place found (None: not checked)
    recall: float | None  # None: no expected facts
    missing_facts: list[str]
    faithfulness: float | None  # None: not judged
    unsupported: list[str]
    language_ok: bool | None
    answered: bool | None  # the answer responds to the question at all
    abstain_ok: bool | None  # abstains exactly when expected (None: not judged)


# Web addresses and phone numbers are checked character for character: an LLM
# judge reads "aydın.edu.tr" (dotless ı, another domain) as "aydin.edu.tr".
_DOMAIN = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:tr|com|org|net|edu)\b")
_PHONE = re.compile(r"\+?\d[\d ()-]{8,}\d")


def literal_claims(answer: str, evidence: str) -> list[tuple[str, bool]]:
    """(literal, supported) for every domain and phone number in ``answer``."""
    text = evidence.lower()
    digits = re.sub(r"\D", "", evidence)
    found = [(d, d.lower() in text) for d in _DOMAIN.findall(answer)]
    for phone in _PHONE.findall(answer):
        number = re.sub(r"\D", "", phone)
        if len(number) >= 10:
            found.append((phone, number in digits))
    return found


def tools_ok(spec: ToolSpec, called: set[str]) -> bool:
    expected = set(spec.required) | set(spec.one_of) | set(spec.allowed)
    if not set(spec.required) <= called:
        return False
    if spec.one_of and not set(spec.one_of) & called:
        return False
    return called <= expected


def _place_id(value: Any) -> str | None:
    return str(value.get("id")) if isinstance(value, dict) else None


def target_ok(question: Question, tools: list[ToolTrace]) -> bool | None:
    routes = [t for t in tools if t.name == "get_route" and isinstance(t.output, dict)]
    if question.route is not None:
        spec = question.route
        return any(
            _place_id(t.output.get("to")) == spec.to
            and _place_id(t.output.get("from")) == spec.start
            and (
                spec.avoid_stairs is None
                or bool(t.args.get("avoid_stairs", False)) == spec.avoid_stairs
            )
            for t in routes
        )
    if question.place is not None:
        found = {_place_id(t.output.get("to")) for t in routes}
        for t in routes:  # an ambiguous name lists its candidates
            found |= {_place_id(item) for item in t.output.get("did_you_mean", [])}
        for t in tools:
            if t.name == "search_places" and isinstance(t.output, list):
                found |= {_place_id(item) for item in t.output}
        return bool(found & set(question.place_ids))
    return None


def score(
    question: Question, trace: RunTrace, verdict: Verdict | None, instructions: str
) -> Score:
    called = [t.name for t in trace.tools]
    context = normalize(" ".join(s for t in trace.tools for s in strings_in(t.output)))
    missing = [fact_label(f) for f in question.facts if not contains_fact(context, f)]
    recall = 1 - len(missing) / len(question.facts) if question.facts else None
    faithfulness: float | None = None
    unsupported: list[str] = []
    language_ok: bool | None = None
    answered: bool | None = None
    abstain_ok: bool | None = None
    if trace.error is not None:
        faithfulness = 0.0
        answered = False
        abstain_ok = False
    elif verdict is not None:
        evidence = instructions + "\n" + "\n".join(t.text for t in trace.tools)
        # Only failed literals are extra claims: a correct URL is already one
        # of the judge's claims and must not count twice.
        failed = sorted(
            {text for text, ok in literal_claims(trace.answer, evidence) if not ok}
        )
        unsupported = [c.text for c in verdict.claims if not c.supported]
        unsupported += [f"literal: {text}" for text in failed]
        total = len(verdict.claims) + len(failed)
        faithfulness = 1 - len(unsupported) / total if total else 1.0
        language_ok = verdict.answer_language == question.lang
        answered = verdict.addresses_question
        # Abstain exactly when expected: "I don't know" to an answerable
        # question has no claims (faithfulness 1.0) but is still wrong, and a
        # reply that ignores the question is no abstention.
        abstain_ok = answered and verdict.abstains == question.abstain
    return Score(
        called=called,
        tool_ok=trace.error is None and tools_ok(question.tools, set(called)),
        target_ok=target_ok(question, trace.tools),
        recall=None if recall is None else round(recall, 3),
        missing_facts=missing,
        faithfulness=None if faithfulness is None else round(faithfulness, 3),
        unsupported=unsupported,
        language_ok=language_ok,
        answered=answered,
        abstain_ok=abstain_ok,
    )


def _mean(values: Iterable[float | bool | None]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return round(sum(present) / len(present), 3) if present else None


def p95(values: Sequence[float]) -> float | None:
    """Nearest-rank 95th percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def summarize(
    scores: Sequence[Score], traces: Sequence[RunTrace]
) -> dict[str, float | None]:
    active = [t.active_seconds for t in traces if t.error is None and t.active_seconds]
    return {
        "correct_tool": _mean(s.tool_ok for s in scores),
        "context_recall": _mean(s.recall for s in scores),
        "faithfulness": _mean(s.faithfulness for s in scores),
        "language_match": _mean(s.language_ok for s in scores),
        "answered": _mean(s.answered for s in scores),
        "abstention": _mean(s.abstain_ok for s in scores),
        "target_place": _mean(s.target_ok for s in scores),
        # Share of questions with a faithfulness score: a judge that gave up
        # must not drop hard answers from the average unnoticed.
        "judged": _mean(s.faithfulness is not None for s in scores),
        # Whole answer (not first token), without pacing waits.
        "latency_p95_s": p95(active),
    }


# --- report -----------------------------------------------------------------


def _cell(value: float | bool | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "ok" if value else "FAIL"
    return f"{value:.2f}"


def print_report(
    questions: Sequence[Question],
    traces: Sequence[RunTrace],
    scores: Sequence[Score],
    summary: dict[str, float | None],
) -> bool:
    header = (
        f"{'id':<12} {'category':<12} {'tools':<5} {'target':<6} {'recall':>6} "
        f"{'faith':>6} {'lang':<5} {'ans':<5} {'abst':<5} {'model':<14} called"
    )
    log("\n" + header + "\n" + "-" * len(header))
    for q, t, s in zip(questions, traces, scores, strict=True):
        model = ",".join(sorted({m.split("/")[-1] for m in t.models})) or "-"
        log(
            f"{q.id:<12} {q.category:<12} {_cell(s.tool_ok):<5} "
            f"{_cell(s.target_ok):<6} {_cell(s.recall):>6} "
            f"{_cell(s.faithfulness):>6} {_cell(s.language_ok):<5} "
            f"{_cell(s.answered):<5} "
            f"{_cell(s.abstain_ok):<5} {model[:14]:<14} "
            f"{','.join(s.called) or '-'}{'  ERROR ' + t.error if t.error else ''}"
        )
    log(f"\n{'metric':<16} {'score':>6} {'target':>7}  status")
    passed = True
    for name, value in summary.items():
        target = TARGETS.get(name)
        if target is None:
            status, shown = "info", "-"
        elif value is None:  # nothing measured (e.g. --no-judge): not a pass
            passed = False
            status, shown = "n/a", f"{target:.2f}"
        else:
            ok = value >= target
            passed &= ok
            status, shown = ("PASS" if ok else "FAIL"), f"{target:.2f}"
        log(f"{name:<16} {_cell(value):>6} {shown:>7}  {status}")
    if (summary.get("judged") or 0.0) < 1.0:
        passed = False
        log("faithfulness does not cover every question (see `judged`): not a pass")
    usage = Counter(m for t in traces for m in t.models)
    log("model responses: " + ", ".join(f"{m} x{n}" for m, n in usage.most_common()))
    return passed


def results_path(tag: str | None) -> Path:
    stem = datetime.now().strftime("%Y-%m-%d") + (f"-{tag}" if tag else "")
    path = RESULTS_DIR / f"{stem}.json"
    n = 2
    while path.exists():
        path = RESULTS_DIR / f"{stem}-{n}.json"
        n += 1
    return path


def write_results(
    path: Path,
    meta: dict[str, Any],
    questions: Sequence[Question],
    traces: Sequence[RunTrace],
    verdicts: Sequence[Verdict | None],
    scores: Sequence[Score],
    summary: dict[str, float | None],
) -> None:
    items = [
        {
            "id": q.id,
            "lang": q.lang,
            "category": q.category,
            "question": q.question,
            "answer": t.answer,
            "error": t.error,
            "tools": [asdict(tool) for tool in t.tools],
            "retrieved": [
                hit
                for tool in t.tools
                if tool.name == "search_knowledge" and isinstance(tool.output, list)
                for hit in tool.output
            ],
            "models": t.models,
            "usage": {
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "requests": t.requests,
            },
            "seconds": t.seconds,
            "active_seconds": t.active_seconds,
            "attempts": t.attempts,
            "judge": v.model_dump() if v is not None else None,
            "score": asdict(s),
        }
        for q, t, v, s in zip(questions, traces, verdicts, scores, strict=True)
    ]
    payload = {"meta": meta, "targets": TARGETS, "summary": summary, "items": items}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shown = path.resolve()
    log(f"results: {shown.relative_to(ROOT) if shown.is_relative_to(ROOT) else shown}")


def knowledge_down(trace: RunTrace) -> bool:
    return any(
        t.name == "search_knowledge"
        and isinstance(t.output, list)
        and any(isinstance(hit, dict) and "error" in hit for hit in t.output)
        for t in trace.tools
    )


def trace_from_item(item: dict[str, Any]) -> RunTrace:
    usage = item.get("usage") or {}
    return RunTrace(
        answer=item["answer"],
        tools=[ToolTrace(**tool) for tool in item["tools"]],
        models=item["models"],
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        requests=usage.get("requests", 0),
        seconds=item["seconds"],
        attempts=item["attempts"],
        error=item["error"],
        active_seconds=item.get("active_seconds", 0.0),
    )


# --- main -------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_settings() -> Settings:
    env_file = ROOT / ".env"
    return Settings(_env_file=env_file if env_file.is_file() else None)  # pyright: ignore[reportCallIssue]


def _from_root(source: str) -> str:
    """Relative paths start at the repository root (where the API runs)."""
    if source.startswith(("http://", "https://")) or Path(source).is_absolute():
        return source
    return str(ROOT / source)


def load_places(cfg: Settings) -> tuple[GraphStore, list[Place]]:
    """The place directory the API serves: the graph and its POIs."""
    store = load_graph(_from_root(cfg.graph_source))
    return store, build_places(store, load_pois(_from_root(cfg.pois_location)))


async def validate(cfg: Settings, questions: Sequence[Question]) -> int:
    """Every fact occurs in a chunk of its language; every place id is routable."""
    _, places = load_places(cfg)
    place_ids = {p.id for p in places}
    problems: list[str] = []
    for q in questions:
        ids = list(q.place_ids)
        if q.route is not None:
            ids += [q.route.start, q.route.to]
        problems += [
            f"{q.id}: {i} is not a routable place" for i in ids if i not in place_ids
        ]
    if not cfg.amap_api_database_url:
        raise SystemExit("--validate needs AMAP_API_DATABASE_URL for the chunks")
    database = Database(cfg.amap_api_database_url)
    await database.open()
    try:
        async with (
            database.pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute("select lang, title, content from amap.chunks")
            rows = await cur.fetchall()
    finally:
        await database.close()
    chunks: dict[str, list[str]] = {"tr": [], "en": []}
    for row in rows:
        chunks.setdefault(row["lang"], []).append(
            normalize(f"{row['title']} {row['content']}")
        )
    for q in questions:
        for fact in q.facts:
            if not any(contains_fact(chunk, fact) for chunk in chunks[q.lang]):
                problems.append(f"{q.id}: fact {fact_label(fact)!r} is in no chunk")
    log(f"checked {len(questions)} questions against {len(rows)} chunks")
    for problem in problems:
        log(f"  {problem}")
    log("question set OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


async def evaluate(args: argparse.Namespace, cfg: Settings) -> int:
    questions_file = Path(args.questions)
    questions = load_questions(questions_file)
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {q.id for q in questions}
        if unknown:
            raise SystemExit(f"unknown question ids: {', '.join(sorted(unknown))}")
        questions = [q for q in questions if q.id in wanted]
    if args.validate:
        return await validate(cfg, questions)

    judge: Judge | None = None
    if not args.no_judge:
        if not cfg.gemini_api_key:
            raise SystemExit("the judge needs GEMINI_API_KEY (or pass --no-judge)")
        judge = Judge(
            client=genai.Client(api_key=cfg.gemini_api_key),
            model=args.judge_model,
            rubric=(EVAL_DIR / args.judge_prompt).read_text("utf-8"),
            pacer=Pacer(min_interval_s=4.0),
        )

    previous: dict[str, RunTrace] = {}
    meta: dict[str, Any] = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "prompt": assistant.PROMPT_PATH.name,
        "judge": None if judge is None else f"{judge.model} ({args.judge_prompt})",
        "questions": questions_file.name,
        "questions_sha256": _sha256(questions_file),
        "judge_sha256": None
        if judge is None
        else _sha256(EVAL_DIR / args.judge_prompt),
    }
    database: Database | None = None
    pacer = Pacer(min_interval_s=args.interval, tokens_per_minute=args.tpm)
    agent: Any = None
    deps_for: dict[str, assistant.AssistantDeps] = {}
    if args.rejudge:
        source = json.loads(Path(args.rejudge).read_text("utf-8"))
        previous = {item["id"]: trace_from_item(item) for item in source["items"]}
        questions = [q for q in questions if q.id in previous]
        meta["rejudged"] = str(args.rejudge)
        meta["prompt"] = source["meta"]["prompt"]
    else:
        store, places = load_places(cfg)
        knowledge: Knowledge | None = None
        if cfg.amap_api_database_url and cfg.gemini_api_key:
            database = Database(cfg.amap_api_database_url)
            await database.open()
            knowledge = Knowledge(database, cfg.gemini_api_key)
        else:
            log("warning: no database or Gemini key, search_knowledge is unavailable")
        model = PacedModel(
            assistant.build_model(cfg.groq_api_key, cfg.gemini_api_key), pacer
        )
        agent = assistant.build_agent(model)
        for lang in ("tr", "en"):
            deps_for[lang] = assistant.AssistantDeps(
                store=store, places=places, knowledge=knowledge, lang=lang
            )
    # The judge checks each answer against the instructions that produced it.
    instructions = (PROMPTS_DIR / meta["prompt"]).read_text("utf-8")
    meta["prompt_sha256"] = _sha256(PROMPTS_DIR / meta["prompt"])

    traces: list[RunTrace] = []
    verdicts: list[Verdict | None] = []
    scores: list[Score] = []
    aborted: str | None = None
    unscored: list[str] = []  # --skip-unavailable: knowledge base was down
    done: list[Question] = []  # scored questions, in order
    try:
        for n, q in enumerate(questions, 1):
            log(f"[{n}/{len(questions)}] {q.id}: {q.question}")
            if q.id in previous:
                trace = previous[q.id]
            else:
                try:
                    trace = await run_question(
                        agent, deps_for[q.lang], q, args.attempts, pacer
                    )
                except QuotaExhaustedError as exc:
                    aborted = f"{q.id}: {exc}"
                    break
                # search_knowledge degrades to an error result instead of
                # failing: answers from a dead knowledge base measure nothing.
                if knowledge_down(trace):
                    if not args.skip_unavailable:
                        aborted = f"{q.id}: knowledge search failed (Gemini quota?)"
                        break
                    unscored.append(q.id)
                    log("    UNSCORED: knowledge search unavailable")
                    continue
            verdict: Verdict | None = None
            if judge is not None and trace.error is None:
                try:
                    verdict = await judge(judge_input(q, trace, instructions))
                except QuotaExhaustedError as exc:
                    aborted = f"{q.id}: judge {exc}"
                    break
                except Exception as exc:  # API, validation, network timeouts
                    # Counted in `judged`; the run goes on.
                    log(f"    judge gave up: {type(exc).__name__}")
            result = score(q, trace, verdict, instructions)
            done.append(q)
            traces.append(trace)
            verdicts.append(verdict)
            scores.append(result)
            log(
                f"    {trace.seconds}s tools={','.join(result.called) or '-'} "
                f"tool_ok={_cell(result.tool_ok)} recall={_cell(result.recall)} "
                f"faith={_cell(result.faithfulness)}"
                + (f" ERROR {trace.error}" if trace.error else "")
            )
    finally:
        if database is not None:
            await database.close()

    summary = summarize(scores, traces)
    meta["finished"] = datetime.now().isoformat(timespec="seconds")
    meta["aborted"] = aborted
    meta["unscored"] = unscored
    write_results(
        Path(args.out) if args.out else results_path(args.tag),
        meta,
        done,
        traces,
        verdicts,
        scores,
        summary,
    )
    passed = print_report(done, traces, scores, summary)
    if unscored:
        passed = False
        log(f"UNSCORED (knowledge base unavailable): {', '.join(unscored)}")
    if aborted is not None:
        log(
            f"\nABORTED after {len(traces)}/{len(questions)} questions: {aborted}\n"
            "Scores above cover the finished questions only; re-run when the "
            "quota is back (answers already saved can be re-scored with --rejudge)."
        )
        return 2
    return 0 if passed else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--only", nargs="+", metavar="ID", help="question ids")
    parser.add_argument(
        "--questions", default=str(QUESTIONS_FILE), help="question set (YAML)"
    )
    parser.add_argument(
        "--validate", action="store_true", help="check facts and places, no LLM"
    )
    parser.add_argument("--no-judge", action="store_true", help="skip faithfulness")
    parser.add_argument(
        "--rejudge", metavar="RESULTS", help="re-score a results file (no agent run)"
    )
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument(
        "--judge-prompt", default=JUDGE_PROMPT, help="rubric file in apps/api/evals"
    )
    parser.add_argument("--tag", help="suffix for the results file name")
    parser.add_argument("--out", help="results file path (overrides --tag)")
    parser.add_argument(
        "--interval", type=float, default=3.0, help="seconds between model requests"
    )
    parser.add_argument(
        "--tpm", type=int, default=7_000, help="model tokens per minute budget"
    )
    parser.add_argument("--attempts", type=int, default=3, help="tries per question")
    parser.add_argument(
        "--skip-unavailable",
        action="store_true",
        help="leave questions unscored when the knowledge base is down, not abort",
    )
    return parser.parse_args(argv)


def main() -> int:
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    args = parse_args()
    return asyncio.run(evaluate(args, load_settings()))


if __name__ == "__main__":
    sys.exit(main())

"""A scripted `Model` test double — no network calls, per CLAUDE.md's "mock
all LLM calls in unit tests." Each `FakeModel` is fed a queue of responses
(plain text, or a tool call); `get_response` pops the next one on each
model turn. Structured `output_type` agents (e.g. the emergency classifier)
are just given a text response whose content is the JSON the SDK validates
against the schema — that's how the Responses API represents structured
output regardless of transport.
"""

import itertools
import json

from agents.items import ModelResponse
from agents.models.interface import Model, ModelTracing
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

_id_counter = itertools.count(1)


def text_response(text: str) -> ModelResponse:
    message = ResponseOutputMessage(
        id=f"msg_fake_{next(_id_counter)}",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(text=text, type="output_text", annotations=[])],
    )
    return ModelResponse(output=[message], usage=Usage(), response_id=None)


def json_response(payload: dict) -> ModelResponse:
    """For structured `output_type` agents — the schema is validated from
    JSON text content, same as any other model response."""
    return text_response(json.dumps(payload))


def clean_turn(reply_text: str) -> list[ModelResponse]:
    """A full non-emergency turn's worth of scripted responses: the
    emergency classifier guardrail runs first (run_in_parallel=False) and
    consumes one model call before the main agent ever runs, then the main
    agent's own response follows. Use this instead of a bare
    `[text_response(...)]` whenever a test goes through the real Triage
    Agent (i.e. anything hitting runner.run_agent_turn / the chat router)."""
    return [json_response({"is_emergency": False}), text_response(reply_text)]


def tool_call_response(name: str, arguments: dict) -> ModelResponse:
    call_id = f"call_fake_{next(_id_counter)}"
    call = ResponseFunctionToolCall(
        id=call_id,
        call_id=call_id,
        type="function_call",
        name=name,
        arguments=json.dumps(arguments),
        status="completed",
    )
    return ModelResponse(output=[call], usage=Usage(), response_id=None)


class FakeModel(Model):
    def __init__(self, responses: list[ModelResponse]):
        self._responses = list(responses)

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing: ModelTracing,
        *,
        previous_response_id,
        conversation_id,
        prompt,
    ) -> ModelResponse:
        if not self._responses:
            raise AssertionError("FakeModel ran out of scripted responses")
        return self._responses.pop(0)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError("FakeModel does not support streaming")

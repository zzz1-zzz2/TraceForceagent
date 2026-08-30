"""MVP4.2 model streaming core tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from coding_agent.agent.loop import run
from coding_agent.config import AgentConfig
from coding_agent.emitter import EventCollector, EventEmitter
from coding_agent.events import ModelCompleted, ModelDelta
from coding_agent.model.client import ModelClient
from coding_agent.model.streaming import ModelStreamAccumulator, ModelStreamDelta
from coding_agent.model.types import TokenUsage


def _chunk(*, text: str = "", finish: str = "", tool_calls=None, usage=None):
    delta = SimpleNamespace(content=text, tool_calls=tool_calls or [])
    choice = SimpleNamespace(delta=delta, finish_reason=finish)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tool(index: int, *, call_id: str = "", name: str = "", args: str = ""):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=args),
    )


def test_accumulator_reassembles_text_and_segmented_tool_arguments() -> None:
    accumulator = ModelStreamAccumulator()
    accumulator.add(ModelStreamDelta(text="inspect "))
    accumulator.add(ModelStreamDelta(
        tool_call_index=0, tool_call_id="call-1", tool_name="read_file",
        arguments_delta='{"path":',
    ))
    accumulator.add(ModelStreamDelta(
        tool_call_index=0, arguments_delta=' "hello.py"}', finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=4, output_tokens=7),
    ))

    response = accumulator.finish()
    assert response.content == "inspect "
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].arguments == {"path": "hello.py"}
    assert response.tool_calls[0].arguments_parse_error is None
    assert response.usage.total == 11


def test_accumulator_preserves_malformed_arguments_as_protocol_diagnostic() -> None:
    accumulator = ModelStreamAccumulator()
    accumulator.add(ModelStreamDelta(
        tool_call_index=0, tool_call_id="call-1", tool_name="read_file",
        arguments_delta='{"path":', finish_reason="tool_calls",
    ))
    call = accumulator.finish().tool_calls[0]
    assert call.arguments == {}
    assert call.raw_arguments == '{"path":'
    assert call.arguments_parse_error


def test_accumulator_keeps_multiple_indexed_calls_in_provider_order() -> None:
    accumulator = ModelStreamAccumulator()
    accumulator.add(ModelStreamDelta(tool_call_index=1, tool_call_id="b", tool_name="b"))
    accumulator.add(ModelStreamDelta(tool_call_index=0, tool_call_id="a", tool_name="a"))
    response = accumulator.finish()
    assert [call.id for call in response.tool_calls] == ["a", "b"]


def test_model_client_normalizes_openai_chunks(monkeypatch) -> None:
    client = ModelClient.__new__(ModelClient)
    client.model = "fake"
    client.temperature = 0.0
    client.max_retries = 1
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: iter([
            _chunk(text="hello "),
            _chunk(tool_calls=[_tool(0, call_id="c1", name="read_file", args='{"path":')]),
            _chunk(tool_calls=[_tool(0, args=' "x.py"}')], finish="tool_calls"),
        ])
    )))
    deltas = list(client.generate_stream([], []))
    accumulator = ModelStreamAccumulator()
    for delta in deltas:
        accumulator.add(delta)
    response = accumulator.finish()
    assert response.content == "hello "
    assert response.tool_calls[0].arguments == {"path": "x.py"}
    assert response.finish_reason == "tool_calls"


def test_agent_loop_emits_transient_deltas_before_durable_completion(monkeypatch, tmp_path) -> None:
    class StreamingModel:
        model = "fake"
        supports_streaming = True

        def generate_stream(self, messages, tools=None):
            yield ModelStreamDelta(text="hello")
            yield ModelStreamDelta(text=" world", finish_reason="stop")

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: StreamingModel()))
    collector = EventCollector()
    emitter = EventEmitter()
    emitter.subscribe(collector)
    result = run(
        "say hello",
        tmp_path,
        AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace"),
        emitter=emitter,
    )
    assert result.reply == "hello world"
    deltas = [event for event in collector.events if isinstance(event, ModelDelta)]
    completed = [event for event in collector.events if isinstance(event, ModelCompleted)]
    assert [event.text for event in deltas] == ["hello", " world"]
    assert all(event.accumulated_text == "" for event in deltas)
    assert completed and completed[0].response.content == "hello world"
    assert collector.events.index(deltas[-1]) < collector.events.index(completed[0])


def test_streaming_duplicate_fragments_are_preserved() -> None:
    accumulator = ModelStreamAccumulator()
    accumulator.add(ModelStreamDelta(text="same"))
    accumulator.add(ModelStreamDelta(text="same"))

    assert accumulator.finish().content == "samesame"


    with pytest.raises(ValueError, match="negative"):
        ModelStreamDelta(tool_call_index=-1)

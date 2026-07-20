from ltm.ai.groq_metrics import (
    begin_call,
    begin_turn,
    clear_call_metrics,
    get_call_metrics,
    get_call_records,
)
from ltm.storage.llm_usage import LLMUsageRepository


def test_metrics_aggregate_actual_provider_calls() -> None:
    begin_turn()
    first = begin_call(stage="initial")
    first.prompt_tokens = 100
    first.completion_tokens = 10
    first.latency_ms = 20.5
    second = begin_call(stage="tool_result")
    second.prompt_tokens = 140
    second.completion_tokens = 30
    second.latency_ms = 35.5

    aggregate = get_call_metrics()

    assert aggregate is not None
    assert aggregate.prompt_tokens == 240
    assert aggregate.completion_tokens == 40
    assert aggregate.latency_ms == 56.0
    assert [record.stage for record in get_call_records()] == ["initial", "tool_result"]


def test_clear_metrics_removes_entire_turn() -> None:
    begin_turn()
    begin_call(stage="initial")

    clear_call_metrics()

    assert get_call_metrics() is None
    assert get_call_records() == ()


def test_usage_repository_counts_every_provider_request() -> None:
    repository = LLMUsageRepository()

    repository.record_usage(
        provider="groq",
        model_id="test-model",
        prompt_tokens=240,
        completion_tokens=40,
        request_count=2,
    )

    totals = repository.get_daily_totals()
    assert totals.request_count == 2
    assert totals.prompt_tokens == 240
    assert totals.completion_tokens == 40

from datetime import date, timedelta

import pytest
from microsoft_teams.ai import Function, ListMemory, UserMessage
from openai.resources.chat.completions.completions import AsyncCompletions
from openai.types.chat import ChatCompletion

from ltm.ai.groq_completions_model import GroqOpenAICompletionsAIModel, terminal_chat_completion
from ltm.ai.groq_metrics import begin_turn, get_call_records
from ltm.bot.context import (
    drain_pending_cards,
    set_turn_context,
    take_terminal_response,
)
from ltm.bot.tools import (
    CreateTaskToolParams,
    acknowledge_task_handler,
    create_task_handler,
    get_task_handler,
    list_tasks_handler,
)
from ltm.domain.enums import DeptCode, Priority
from ltm.domain.models import AcknowledgeTaskParams, GetTaskParams, ListTasksParams, UserRef
from ltm.policy.assignment import clear_policy_cache
from ltm.policy.profiles import clear_profile_cache


@pytest.fixture(autouse=True)
def clear_assignment_caches():
    clear_profile_cache()
    clear_policy_cache()
    yield
    clear_profile_cache()
    clear_policy_cache()


def test_terminal_completion_has_normal_assistant_shape_without_provider_metric() -> None:
    begin_turn()

    response = terminal_chat_completion(content="Review and confirm the task card.", model="test-model")

    assert response.choices[0].message.content == "Review and confirm the task card."
    assert response.choices[0].message.tool_calls is None
    assert get_call_records() == ()


@pytest.mark.asyncio
async def test_successful_create_task_produces_card_and_terminal_response(monkeypatch) -> None:
    directory = {
        "version": 1,
        "employees": {"actor": {"department_code": "IT", "active": True}},
    }
    policy = {
        "version": 1,
        "defaults": {"allow_same_department": True, "allow_cross_department": False},
        "edges": [],
        "deny_edges": [],
    }
    monkeypatch.setattr("ltm.policy.profiles.load_assignment_directory", lambda: directory)
    monkeypatch.setattr("ltm.policy.assignment.load_assignment_policy", lambda: policy)
    clear_profile_cache()
    clear_policy_cache()
    actor = UserRef(entra_object_id="actor", display_name="Creator")
    set_turn_context(conversation_id="conversation", actor=actor)
    params = CreateTaskToolParams(
        task_type="Review",
        description="Review the optimization change",
        assignee_entra_id="actor",
        assignee_display_name="Creator",
        assignee_department_code=DeptCode.IT,
        priority=Priority.MEDIUM,
        due_date=str(date.today() + timedelta(days=1)),
    )

    result = await create_task_handler(params)

    assert result == take_terminal_response()
    assert len(drain_pending_cards()) == 1
    assert take_terminal_response() is None


@pytest.mark.asyncio
async def test_successful_create_uses_one_external_provider_call(monkeypatch) -> None:
    directory = {
        "version": 1,
        "employees": {"actor": {"department_code": "IT", "active": True}},
    }
    policy = {
        "version": 1,
        "defaults": {"allow_same_department": True, "allow_cross_department": False},
        "edges": [],
        "deny_edges": [],
    }
    monkeypatch.setattr("ltm.policy.profiles.load_assignment_directory", lambda: directory)
    monkeypatch.setattr("ltm.policy.assignment.load_assignment_policy", lambda: policy)
    clear_profile_cache()
    clear_policy_cache()
    set_turn_context(
        conversation_id="single-call-conversation",
        actor=UserRef(entra_object_id="actor", display_name="Creator"),
    )
    due_date = str(date.today() + timedelta(days=1))
    provider_calls = 0

    async def fake_create(_self, *args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return ChatCompletion.model_validate(
            {
                "id": "provider-tool-selection",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "index": 0,
                        "logprobs": None,
                        "message": {
                            "content": None,
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "create-call",
                                    "type": "function",
                                    "function": {
                                        "name": "create_task",
                                        "arguments": (
                                            '{"task_type":"Review","description":"Review change",'
                                            '"assignee_entra_id":"actor","assignee_display_name":"Creator",'
                                            '"assignee_department_code":"IT","priority":"Medium",'
                                            f'"due_date":"{due_date}"}}'
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "created": 0,
                "model": "test-model",
                "object": "chat.completion",
            }
        )

    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    model = GroqOpenAICompletionsAIModel(
        model="test-model",
        key="not-used",
        base_url="https://example.invalid/v1",
    )
    governed_calls = 0

    async def govern() -> None:
        nonlocal governed_calls
        governed_calls += 1

    model.set_before_provider_call(govern)
    function = Function[CreateTaskToolParams](
        name="create_task",
        description="Create a task draft.",
        parameter_schema=CreateTaskToolParams,
        handler=create_task_handler,
    )
    begin_turn()

    response = await model.generate_text(
        UserMessage(content="Create a review task for me tomorrow."),
        memory=ListMemory(),
        functions={"create_task": function},
    )

    assert provider_calls == 1
    assert governed_calls == 1
    assert response.content and "confirmation card" in response.content
    assert len(get_call_records()) == 1
    assert len(drain_pending_cards()) == 1


@pytest.mark.asyncio
async def test_denied_create_returns_terminal_policy_message() -> None:
    set_turn_context(
        conversation_id="denied-conversation",
        actor=UserRef(entra_object_id="unknown-actor"),
    )
    params = CreateTaskToolParams(
        task_type="Review",
        description="This should be denied",
        assignee_entra_id="unknown-assignee",
        assignee_department_code=DeptCode.IT,
        due_date=str(date.today() + timedelta(days=1)),
    )

    result = await create_task_handler(params)

    assert "not listed" in result
    assert take_terminal_response() == result
    assert drain_pending_cards() == []


@pytest.mark.asyncio
async def test_list_tasks_produces_terminal_user_facing_response() -> None:
    set_turn_context(
        conversation_id="list-conversation",
        actor=UserRef(entra_object_id="actor"),
    )

    result = await list_tasks_handler(ListTasksParams(filter="my_tasks"))

    assert result == take_terminal_response()
    assert "task" in result.lower()
    assert drain_pending_cards() == []


@pytest.mark.asyncio
async def test_known_lifecycle_error_is_terminal() -> None:
    set_turn_context(
        conversation_id="lifecycle-error",
        actor=UserRef(entra_object_id="actor"),
    )

    result = await acknowledge_task_handler(AcknowledgeTaskParams(task_id="missing"))

    assert '"code": "NOT_FOUND"' in result
    assert take_terminal_response() == "Task not found."


@pytest.mark.asyncio
async def test_task_search_is_terminal_and_compact() -> None:
    set_turn_context(
        conversation_id="task-search",
        actor=UserRef(entra_object_id="actor"),
    )

    result = await get_task_handler(GetTaskParams(query="does-not-exist"))

    terminal = take_terminal_response()
    assert terminal is not None and "no matching open tasks" in terminal
    assert '"value"' not in result

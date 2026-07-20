from microsoft_teams.ai import ModelMessage, UserMessage

from ltm.ai.memory_trim import trim_messages


def test_memory_character_budget_removes_oldest_complete_turn() -> None:
    messages = [
        UserMessage(content="a" * 40),
        ModelMessage(content="b" * 40, function_calls=None),
        UserMessage(content="latest question"),
        ModelMessage(content="latest answer", function_calls=None),
    ]

    trimmed = trim_messages(messages, max_turns=4, max_chars=50)

    assert [message.content for message in trimmed] == ["latest question", "latest answer"]


def test_memory_budget_never_discards_the_latest_turn() -> None:
    messages = [UserMessage(content="x" * 100)]
    assert trim_messages(messages, max_turns=4, max_chars=10) == messages


def test_character_budget_still_applies_when_turn_limit_is_disabled() -> None:
    messages = [
        UserMessage(content="old" * 20),
        ModelMessage(content="answer" * 20, function_calls=None),
        UserMessage(content="latest"),
    ]
    assert trim_messages(messages, max_turns=0, max_chars=20) == [messages[-1]]

from microsoft_teams.ai import Function
from pydantic import BaseModel

from ltm.ai.tool_selection import select_tools_for_message


class Empty(BaseModel):
    pass


def _functions() -> list[Function]:
    return [
        Function(name=name, description=name, parameter_schema=Empty, handler=lambda _: "ok")
        for name in ("acknowledge_task", "close_task", "get_task_status", "list_tasks", "create_task")
    ]


def test_high_confidence_intent_exposes_only_relevant_tool() -> None:
    selected = select_tools_for_message(_functions(), "Please acknowledge LTM-IT-2026-0001")
    assert [tool.name for tool in selected] == ["acknowledge_task"]


def test_ambiguous_message_keeps_all_tools() -> None:
    functions = _functions()
    assert select_tools_for_message(functions, "Can you help me with this?") == functions


def test_d365_lookup_does_not_get_misrouted_to_task_status() -> None:
    functions = _functions()
    assert select_tools_for_message(functions, "Look up purchase order PO-123") == functions


def test_natural_list_request_selects_list_tool() -> None:
    selected = select_tools_for_message(_functions(), "Could you show all tasks assigned to Finance?")
    assert [tool.name for tool in selected] == ["list_tasks"]

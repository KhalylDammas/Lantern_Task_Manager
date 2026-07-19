"""Groq tool-calling evaluation scenarios (C09)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

EvalExpectation = Literal["tool", "no_tool", "no_bogus_xml"]


@dataclass(frozen=True)
class EvalScenario:
    name: str
    turn_json: dict[str, Any]
    expectation: EvalExpectation
    expected_tool: str | None = None


def eval_scenarios() -> list[EvalScenario]:
    actor = {
        "entra_object_id": "11111111-1111-1111-1111-111111111111",
        "display_name": "Test User",
        "department": "Finance",
        "department_code": "FIN",
    }
    base = {
        "schema_version": "1.0",
        "turn": {"activity_id": "eval-1", "timestamp": "2026-06-29T12:00:00Z"},
        "actor": actor,
        "conversation": {"id": "eval-conv", "type": "personal", "is_group": False},
        "capabilities": {"graph_enabled": True, "tool_profile": "full"},
    }
    return [
        EvalScenario(
            name="create_task_resolved_mention",
            turn_json={
                **base,
                "message": "Create a high priority FIN task due 2026-07-15: review Q2 budget for @Alice",
                "enrichments": {
                    "mentions": {
                        "resolved": [
                            {
                                "token": "@Alice",
                                "assignee_entra_id": "22222222-2222-2222-2222-222222222222",
                                "assignee_display_name": "Alice Finance",
                                "assignee_department_code": "FIN",
                            }
                        ],
                        "ambiguous": [],
                    }
                },
            },
            expectation="tool",
            expected_tool="create_task",
        ),
        EvalScenario(
            name="list_my_tasks",
            turn_json={
                **base,
                "message": "Show my tasks",
            },
            expectation="tool",
            expected_tool="list_tasks",
        ),
        EvalScenario(
            name="close_task",
            turn_json={
                **base,
                "message": "Close LTM-FIN-2026-0001 with notes: completed review",
                "enrichments": {"task_references": ["LTM-FIN-2026-0001"]},
            },
            expectation="tool",
            expected_tool="close_task",
        ),
        EvalScenario(
            name="get_task_status",
            turn_json={
                **base,
                "message": "Status of LTM-FIN-2026-0001",
                "enrichments": {"task_references": ["LTM-FIN-2026-0001"]},
            },
            expectation="tool",
            expected_tool="get_task_status",
        ),
        EvalScenario(
            name="reopen_task",
            turn_json={
                **base,
                "message": "Reopen LTM-FIN-2026-0001: the bank letter is missing, needs rework",
                "enrichments": {"task_references": ["LTM-FIN-2026-0001"]},
            },
            expectation="tool",
            expected_tool="reopen_task",
        ),
        EvalScenario(
            name="resume_task",
            turn_json={
                **base,
                "message": "Resume work on LTM-FIN-2026-0001",
                "enrichments": {"task_references": ["LTM-FIN-2026-0001"]},
            },
            expectation="tool",
            expected_tool="resume_task",
        ),
        EvalScenario(
            name="query_d365_po",
            turn_json={
                **base,
                "message": "Look up PO PO-2300001005 before we create the task",
            },
            expectation="tool",
            expected_tool="query_d365_po",
        ),
        EvalScenario(
            name="query_d365_vendor",
            turn_json={
                **base,
                "message": "Find vendor V-10023",
            },
            expectation="tool",
            expected_tool="query_d365_vendor",
        ),
        EvalScenario(
            name="ambiguous_mention_no_create",
            turn_json={
                **base,
                "message": "Create a task for @Bob",
                "enrichments": {
                    "mentions": {
                        "resolved": [],
                        "ambiguous": [
                            {
                                "token": "@Bob",
                                "query": "Bob",
                                "candidates": [
                                    {"assignee_entra_id": "a", "display_name": "Bob One"},
                                    {"assignee_entra_id": "b", "display_name": "Bob Two"},
                                ],
                            }
                        ],
                    }
                },
            },
            expectation="no_tool",
        ),
        EvalScenario(
            name="reject_bogus_xml_tool_output",
            turn_json={
                **base,
                "message": "List overdue tasks",
            },
            expectation="no_bogus_xml",
        ),
    ]


def score_result(
    scenario: EvalScenario,
    *,
    tool_names: list[str],
    text_content: str | None,
) -> tuple[bool, str]:
    content = text_content or ""
    if scenario.expectation == "no_bogus_xml":
        if "<function=" in content.lower():
            return False, "model emitted bogus XML tool syntax"
        return True, "ok"
    if scenario.expectation == "no_tool":
        if "create_task" in tool_names:
            return False, "create_task called despite ambiguous mention"
        return True, "ok"
    if scenario.expectation == "tool":
        if scenario.expected_tool not in tool_names:
            return False, f"expected tool {scenario.expected_tool}, got {tool_names}"
        return True, "ok"
    return False, f"unknown expectation {scenario.expectation}"

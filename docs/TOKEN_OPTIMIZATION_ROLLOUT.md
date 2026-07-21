# Token Optimization Rollout

Date: 2026-07-20

## Implemented

- Actual Groq provider calls and aggregate per-turn tokens/latency are measured.
- Daily request counts include recursive tool-result requests.
- Successful task creation, task lists, task lookup/search, lifecycle actions,
  draft actions, and known tool errors use deterministic terminal responses.
- Groq and Anthropic skip the model paraphrasing request for terminal results.
- Task detail lookup renders an Adaptive Card; searches render the existing
  Markdown list.
- Tool-memory results omit full task objects.
- High-confidence intents expose a narrow tool schema; ambiguous messages retain
  all configured tools.
- LLM input omits transport-only identifiers and empty actor fields.
- System instructions were reduced from about 4.2 KB to about 2.0 KB.
- Conversation memory is bounded by turns, individual tool-result size, and total
  approximate character size.
- Help, common list commands, forms, directory lookup commands, and card actions
  continue to bypass the model entirely.

## Rollback controls

- `LLM_TERMINAL_RESPONSES_ENABLED=false` restores model-generated follow-up
  responses after tool execution.
- `LLM_DYNAMIC_TOOLS_ENABLED=false` restores the complete tool schema on every
  model turn.
- `LLM_MEMORY_MAX_CHARS=0` disables the new aggregate memory character budget.

These controls do not bypass authorization or change the task state machine.

## Dev verification

Compare representative turns before and after deployment:

| Flow | Expected external calls |
| --- | ---: |
| Help, exact list command, form, card action | 0 |
| Plain conversational response | 1 |
| Terminal tool flow | 1 |
| Non-terminal/D365 reasoning flow | 2 or more |

Check logs for `provider_calls`, `tool_result_calls`, `selected_tools`, and
`llm_terminal_response ... external_call_skipped=1`. Compare prompt/completion
tokens and latency for the same scripted requests.

Smoke-test create/confirm, acknowledge, close, verify, reopen, resume, task detail,
task search, empty lists, authorization denials, and notification warnings. Disable
the two flags independently if behavior differs from the established baseline.

# Agent Framework Migration Assessment

Date: 2026-07-20

## Decision summary

The deprecated `microsoft-teams-ai` layer should eventually be replaced, but a
framework migration should not be justified as a fix for the observed two model
API calls. Those calls are the expected function-calling protocol:

1. The model selects a function and supplies its arguments.
2. The application executes the function and sends its result back to the model.
3. The model creates the final user-facing response.

Microsoft Agent Framework uses the same loop by default. Migrating without
changing the interaction design would therefore preserve the second model call.

Recommendation: treat migration as a maintainability and support-lifecycle
project. Treat call-count and token reduction as a separate optimization project.

## Evidence in the current runtime

`src/app.py` creates a `ChatPrompt` with registered functions and calls
`ChatPrompt.send()` once. The installed OpenAI-compatible adapter then performs
the loop internally. In
`.venv/lib/python3.12/site-packages/microsoft_teams/openai/completions_model.py`,
`generate_text()`:

- makes a chat-completions request;
- detects `model_response.function_calls`;
- recursively invokes itself;
- executes the pending functions; and
- includes their results in the next model request.

The custom Anthropic adapter implements the equivalent two-request sequence.
Consequently, application telemetry can correctly record two provider calls even
though `run_ai_turn()` calls the prompt only once.

A turn that does not select a function should normally use one model call. A turn
that selects one or more local functions normally needs at least two. Instrumented
request IDs should be used to confirm this distinction before changing behavior.

## Migration scope

The recent runtime-spine separation makes this a bounded adapter migration rather
than a full application rewrite. The Teams host, HTTP routes, cards, application
use cases, repositories, authorization rules, persistence, and notification
delivery can remain in place.

The following AI-boundary components would change:

- `ChatPrompt`, `AIModel`, `Function`, `ListMemory`, and message types;
- the Groq/OpenAI-compatible model adapter;
- the custom Anthropic model adapter;
- function schema registration and invocation wrappers;
- conversation/session memory and trimming;
- streaming callbacks;
- retry, fallback, rate-governor, and usage telemetry integration; and
- the pending-card side channel used by function handlers.

Provider compatibility deserves an explicit spike. The application uses Groq's
OpenAI-compatible endpoint and a custom Anthropic path, so examples that only
exercise native OpenAI or Azure OpenAI are not sufficient proof.

## Difficulty and risk

Assessment: **medium-to-high effort, moderate migration risk**.

This is not dangerous to production if introduced behind an internal runtime
interface and feature flag. A big-bang replacement would be risky because defects
could duplicate state-changing actions, weaken authorization boundaries, lose
conversation state, or break Teams card delivery while still returning plausible
chat text.

A reasonable planning estimate is 4-7 engineering days for a parity spike and
careful implementation, or roughly 1-2 weeks when dev-environment soak testing,
provider fallbacks, and regression work are included. This is an estimate, not a
commitment; the Groq and Anthropic compatibility spike is the main uncertainty.

## Safe implementation methodology

1. Add per-turn telemetry that identifies provider calls, tool-selection calls,
   tool-result calls, selected tools, latency, and tokens. Do not log secrets or
   sensitive tool payloads.
2. Define a small application-owned `AgentRuntime` interface. Keep framework
   objects from crossing into use cases, repositories, or Teams handlers.
3. Implement Agent Framework as a second adapter behind a configuration flag.
4. Start with Groq and a small read-only tool set. Prove plain chat, one tool call,
   multi-tool behavior, memory, errors, cancellation, and streaming.
5. Add state-changing lifecycle tools only after idempotency and authorization
   tests pass. Ensure a retry cannot acknowledge or close a task twice.
6. Port the card-result channel, Anthropic fallback, rate governor, and usage
   accounting.
7. Run transcript parity tests and compare call count, tokens, latency, and tool
   outcomes against the existing adapter.
8. Enable only in `dev`, canary by conversation or user, retain rapid rollback,
   and remove the deprecated adapter only after the new path is proven.

## Call and token optimization (separate workstream)

The most direct way to eliminate the second model call for common operations is
to make selected tools terminal: after the model selects and the application
executes a tool, the host renders a deterministic response/card from a typed
result instead of asking the model to paraphrase it. Even better, deterministic
commands and card actions can bypass the model entirely.

Additional opportunities:

- expose only tools relevant to the current state and user intent;
- keep tool descriptions and result payloads compact;
- use typed presentation models rather than sending rendered tables through the
  model;
- provide deterministic prompt-suggestion and card-detail responses; and
- reduce conversational repair turns with clearer cards and next-action choices.

These optimizations can be implemented on the current framework or the new one.
They require product decisions about which responses may be deterministic and
which still need natural-language reasoning.

## Official references

- [Microsoft Agent Framework: Adding tools](https://learn.microsoft.com/en-us/agent-framework/journey/adding-tools)
- [Teams SDK: Function/tool calling](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/in-depth-guides/ai/function-calling)
- [Microsoft Teams SDK overview](https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/build-and-test/tool-sdk-overview)
- [Agent Framework Python 2026 significant changes](https://learn.microsoft.com/en-us/agent-framework/support/upgrade/python-2026-significant-changes)

## Deferred discussion

The broader token-usage proposal (pre-determined responses, typed placeholders,
and fewer user-agent turns) is intentionally deferred. It should resume as a
separate design exercise after measurement establishes the highest-cost paths.

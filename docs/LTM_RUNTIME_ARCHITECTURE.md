# LTM Runtime Architecture

This is the implementation-facing guide to the active request path. It supersedes
the runtime assumptions in the pre-code architecture document where they differ.

## Dependency direction

```text
Teams cards/messages ─┐
                     ├─> application use cases ─> repositories/domain
LLM tools ────────────┘             │
                                    └─> notification orchestration
```

- `src/app.py` composes the Microsoft Teams SDK and delegates actions.
- `ltm.bot.card_actions` parses and routes Adaptive Card verbs.
- `ltm.bot.tools` and `ltm.bot.d365_tools` expose lifecycle and D365 functions separately.
- `ltm.application` owns authorization, transaction boundaries, lifecycle orchestration,
  and transport-neutral result codes.
- `ltm.storage` owns persistence; transport adapters must not import task repositories or ORM models.

## Interaction contract

Essential task actions are available from both cards and chat. New cards use canonical
verbs such as `task.acknowledge`, `task.view`, `task.verify`, and `draft.confirm`.
Legacy verbs remain routed as compatibility aliases for one release.

LLM lifecycle tools return a consistent envelope containing `ok`, `code`, `message`,
`value`, and `warnings`. A successful state change remains successful when notification
delivery fails; the failure is reported through `warnings` and logs.

## Change rules

1. Add or change lifecycle behavior in `ltm.application`, not in a card or tool handler.
2. Keep adapters limited to payload parsing, use-case invocation, and response rendering.
3. Add card/chat parity tests for new essential lifecycle actions.
4. Do not introduce a second settings model; use `ltm.config.settings.Settings`.
5. Delete compatibility aliases after their documented release window.

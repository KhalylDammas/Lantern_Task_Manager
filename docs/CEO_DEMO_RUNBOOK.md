# CEO demo runbook

## Ten minutes before

1. Open the personal chat with **Lantern Task Manager dev** in Teams.
2. Warm the Free App Service plan and confirm every dependency is ready:

   ```bash
   curl --fail --show-error --max-time 60 \
     https://ltmdev02.azurewebsites.net/health | jq .
   ```

   Continue only when the response has `status: "ok"`, `graph.ok: true`,
   `database.ok: true`, and `llm.ok: true`.
3. Send `help`, then `my tasks`, to warm the Teams/Bot Framework path.
4. Keep the health endpoint open in a second window. The F1 plan can cold-start
   after inactivity, so repeat the health request immediately before presenting.

## Recommended showcase flow

1. **Natural language:** Ask LTM to assign a realistic task to a direct report,
   with a type, description, priority, and due date in one message.
2. **Identity safety:** Point out the resolved employee, department, email, and
   job title on the confirmation card. Click **Confirm**.
3. **Traceability:** Ask for `my requests`, then open the new task's details.
4. **Lifecycle:** From the assignee account, acknowledge the task, close it with
   completion notes, and show the verifier card.
5. **Governance:** Confirm or reject completion from the configured verifier.
6. **Resilience:** Type `form` to show that task capture still works without the
   language model. Mention that D365 tools are read-only.

## Guardrails and recovery

- A task is not persisted until **Confirm** is clicked on its Adaptive Card.
- Do not demonstrate with real sensitive financial or employee data.
- If the model path fails, use `form`; this bypasses model extraction while
  retaining the same assignment-policy and confirmation checks.
- If Teams appears idle, check `/health`. A first request on F1 may take longer
  because the Free tier does not support Always On.
- If Graph is degraded, avoid `/who` and free-text names; use an explicit Teams
  `@mention` or the structured form after Graph recovers.

## Post-demo engineering work

- Plan migration from the deprecated Microsoft Teams AI alpha packages to
  Microsoft Agent Framework as a separately tested change.
- Persist draft/disambiguation state if the service scales beyond one process.
- Add role-based reporting scopes beyond the current participant, verifier, and
  CEO task-detail policy.
- Add end-to-end tests against non-production Graph, Teams, D365, and Turso.

# Low-Friction Interaction Rollout

## Database

Run `alembic upgrade head` before starting the updated app. Migration
`20260721_01` adds durable interaction sessions and revisioned task drafts. The
application defaults to a 30-minute pending-operation and draft lifetime.

## Feature controls

- `LTM_INTERACTION_COORDINATOR_ENABLED=true`
- `LTM_SELF_CLOSE_AUTO_VERIFY_ENABLED=true`
- `LTM_SELF_NOTIFICATION_ACTIVITY_ONLY_ENABLED=true`

Deploy to `dev` first. The self-close flag can be disabled independently without
changing ordinary creator/verifier closure behavior. The notification flag can be
disabled to restore configured bot-DM delivery for the acting user.

## Dev smoke test

1. Create a complete task for yourself using “normal” and “tomorrow”; expect one
   read-only confirmation card after one message.
2. Correct its priority in chat; expect a new card and an expired old confirmation.
3. Confirm, acknowledge, and close it; provide notes in the next chat message.
   With creator, assignee, and verifier all equal, expect `VERIFIED` and no
   verification card or bot DM.
4. Create a task for another user and verify the ordinary acknowledgment and
   `PENDING_VERIFICATION` workflow.
5. Restart the app between a Close click and its notes; expect the pending close
   to continue.
6. Invoke the same card action twice; expect one transition and one notification.

Monitor `turns_before_card`, `draft_normalized`, duplicate notification receipts,
stale-response log entries, and outbound messages per interaction.

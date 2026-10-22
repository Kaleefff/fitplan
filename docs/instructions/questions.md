# Open questions

Agents add a line when a spec is silent or contradictory: `- [task id] question. Proposed default: ... (open)`. A human answers by changing the spec files, then deletes the line. Answered questions are not kept here.

All questions up to 19 Oct 2026 (including B-01, D-04 and D-03 of that day) are answered in `algorithms.md`, `api-rules.md`, `decisions.md` (D17–D23) and `tasks.md` (DB-01).
- [B-16] Section 6 progression is `planned_weight + step`, but a weighted exercise can still have `planned_weight` NULL after a workout with only 0 kg sets (no baseline). Proposed default: no progression for it until a set with weight > 0 sets the baseline. (open)
- [DB-01] `client_uuid` is unique across all users (tasks.md DB-01 item 13), so a create from user B that repeats user A's UUID can neither be stored nor answered with A's row, and api-rules.md does not say what B gets. Proposed default: unique per user, `UNIQUE (user_id, client_uuid)` on `workout_log`, `nutrition_log` and `body_metrics`, as migration 0002. (open)

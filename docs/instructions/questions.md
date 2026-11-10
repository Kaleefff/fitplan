# Open questions

Agents add a line when a spec is silent or contradictory: `- [task id] question. Proposed default: ... (open)`. A human answers by changing the spec files, then deletes the line. Answered questions are not kept here.


- [M-10, B-11] Should the user choose a preferred training intensity when generating a plan (light / standard / hard)? The request (`GenerateTrainingPlanRequest`) has no such field, so the app cannot offer it. Proposed default: an optional `intensity` field, default `standard` (today's behaviour, `algorithms.md` 4.7 unchanged); `light` = one set fewer per exercise (min 2) and rest +30 s; `hard` = one set more per exercise (max 6) and rest −15 s (min 30 s); the value is stored on `training_plan` and returned in `TrainingPlan`, so "generate again" keeps it; adaptation (section 6) is unchanged. Needs a contract PR (API and APP) and a migration (DATA). (open)

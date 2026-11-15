# Open questions

Agents add a line when a spec is silent or contradictory: `- [task id] question. Proposed default: ... (open)`. A human answers by changing the spec files, then deletes the line. Answered questions are not kept here.


- [M-10, B-11] Should the user choose a preferred training intensity when generating a plan (light / standard / hard)? The request (`GenerateTrainingPlanRequest`) has no such field, so the app cannot offer it. Proposed default: an optional `intensity` field, default `standard` (today's behaviour, `algorithms.md` 4.7 unchanged); `light` = one set fewer per exercise (min 2) and rest +30 s; `hard` = one set more per exercise (max 6) and rest −15 s (min 30 s); the value is stored on `training_plan` and returned in `TrainingPlan`, so "generate again" keeps it; adaptation (section 6) is unchanged. Needs a contract PR (API and APP) and a migration (DATA). (open)
- [B-22] `algorithms.md` 10 step 1: which meal type must a single food fit for 5.2? Proposed default: at least one meal type of the active plan's slots (5.1), so a 3-meal plan never suggests a snack-only food. (open)
- [B-22] `algorithms.md` 10 step 4: when a remaining macro is 0 or negative, its ideal is not positive and the term divides by it. Proposed default: that macro is left out of the score. (open)
- [B-22] `algorithms.md` 10 step 4: tie-break between equal scores. Proposed default: planned meals first, then by meal or food id. (open)
- [B-22] `Suggestion` of a planned meal: what are `name`, `grams` and `nutrition`? Proposed default: `name` = "<Meal type>: <food names>" (for example "Lunch: Chicken breast, Rice"), `grams` = the sum of the item grams, `nutrition` = the meal's stored planned kcal and macros. A food with 0 kcal gets its largest portion (the limit of step 2). (open)

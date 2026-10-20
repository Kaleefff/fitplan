# Algorithms

Formulas, constants and test vectors. The vectors are unit tests. Constants live in one backend module (`app/domain/constants.py`). Column names are those of `database/init/01_schema.sql` after DB-01. If this file is silent, do not invent: add a question to `questions.md`.

## 0. Constants

| Name | Value | Used in |
| --- | --- | --- |
| Age / height / weight, target weight | 16–100 years / 120–250 cm / 30–300 kg | FR-U7 |
| PAL offered | sedentary 1.2, light 1.375, moderate 1.55, high 1.725, very high 1.9 (DB accepts 1.200–2.500) | FR-U6 |
| RPE, hunger | integers 1–10 | FR-A2, FR-A3 |
| Password | 8–72 bytes, at least one letter and one digit | FR-U1 |
| Training days / meals per day | 1–7 / 3–5 | FR-P1, FR-P6 |
| Plan duration | 56 days (`end_date = start_date + 56`) | FR-P7 |
| Photo upload | JPEG, PNG or WebP, ≤ 8 MB (request ≤ 9 MiB) | FR-N1 |
| Recognition expiry | 6 h | FR-N4 |
| Recognition candidates K / low confidence | 3 / < 0.30 | FR-N2 |
| Weight step / rounding | 2.5 kg | 6 |
| Diet search | stage 1: 5 attempts; stage 2: `DIET_EXTRA_ATTEMPTS` 12, `DIET_MEAL_CANDIDATES` 8, `GOOD_MEAL_ERROR` 0.01 | 5.5 |
| Seed kcal check | \|kcal − (4P + 4C + 9F)\| ≤ max(12 % of kcal, 15 kcal) | DB-04 |

Rounding: half up. Kcal are integers; grams and macros one decimal in responses. Hunger is stored and reported and never changes a plan.

## 1. Energy (FR-P4)

BMR (Mifflin-St Jeor) = `10·kg + 6.25·cm − 5·age + s`, `s` = +5 male, −161 female, −78 other. TDEE = round(BMR × PAL). `user_profile.tdee` is recomputed whenever age, sex, weight, height or PAL changes.

## 2. Targets by goal (FR-P5)

1. `target_kcal = round(TDEE × factor)`, at least 1500 (male) or 1200 (female, other).
2. `protein_g = min(g_per_kg × kg, 0.35 × target_kcal / 4)`.
3. `fat_g = fat_share × target_kcal / 9`.
4. `carbs_g = (target_kcal − 4·protein_g − 9·fat_g) / 4` (never below 35 % of kcal with these values).

| Goal | kcal factor | protein g/kg | fat share |
| --- | --- | --- | --- |
| weight_loss | 0.80 | 2.0 | 0.30 |
| muscle_gain | 1.10 | 1.8 | 0.25 |
| strength | 1.05 | 1.8 | 0.25 |
| maintenance, general_fitness | 1.00 | 1.6 | 0.30 |
| endurance | 1.05 | 1.4 | 0.20 |

| Input (sex, kg, cm, age, PAL, goal) | Result |
| --- | --- |
| male, 80, 180, 25, 1.55, muscle_gain | BMR 1805.0, TDEE 2798, 3078 kcal, P 144.0, F 85.5, C 433.1 |
| female, 60, 165, 30, 1.375, weight_loss | BMR 1320.3, TDEE 1815, 1452 kcal, P 120.0, F 48.4, C 134.1 |
| female, 55, 155, 60, 1.2, weight_loss | BMR 1057.8, TDEE 1269, 1200 kcal (floor), P 105.0, F 40.0, C 105.0 |
| male, 120, 185, 35, 1.375, weight_loss | BMR 2186.3, TDEE 3006, 2405 kcal, P 210.4 (cap), F 80.2, C 210.4 |

## 3. Muscle groups (FR-P2)

Seeded groups and region (region sets the progression step): chest, back, shoulders, biceps, triceps (upper); quadriceps, hamstrings, glutes, calves (lower); core (core). Main groups: muscle_gain = all ten; every other goal = chest, back, shoulders, quadriceps, hamstrings, glutes, core.

## 4. Training plan (FR-P1, P2, P3, P7)

**4.1 Inputs.** Goal, training days, experience level and equipment (the last two default to the profile and are stored on the plan as a snapshot), the user's active injuries.

**4.2 Eligible exercise.** `difficulty_level ≤ experience_level` (beginner < intermediate < advanced); `equipment ≤ user equipment` (none < home < gym); not excluded by 4.3. Tiers: pull-up bar, bench, dumbbells and bands are `home`; chair, wall and towel are `none`.

**4.3 Injuries.** For each active injury an exercise is excluded when (1) it is listed in `injury_type_excluded_exercise` for the injury type, (2) its primary group is the injury's `affected_muscle_group_id`, or (3) severity is moderate or severe and the affected group is one of its secondary groups. A main group left with no exercise only because of injuries is skipped: stored in `training_plan.skipped_muscle_group_ids`, returned as `skipped_groups` with reason `injury`. Required groups = main groups − skipped.

**4.4 Not enough exercises (FR-P3).** If a required group has no eligible exercise because of level or equipment, return 422 `insufficient_exercises`, store nothing, keep the previous draft. `details`: one `{field: "muscle_group", code: "no_eligible_exercise", muscle_group}` per empty group, then `{code: "change_equipment", equipment}` (lowest higher tier covering every required group) and `{code: "change_goal", goals: [...]}` (goals fully covered with current settings) when they exist. If every group is skipped for injuries, the same 422 without suggestions.

**4.5 Split.**

| Days | Sessions | Weekdays |
| --- | --- | --- |
| 1 | Full Body | wed |
| 2 | Full Body A, B | mon, thu |
| 3 | Full Body A, B, C | mon, wed, fri |
| 4 | Upper A, Lower A, Upper B, Lower B | mon, tue, thu, fri |
| 5 | Upper, Lower, Push, Pull, Legs | mon, tue, thu, fri, sat |
| 6 | Push, Pull, Legs ×2 | mon–sat |
| 7 | Push, Pull, Legs ×2, Full Body | mon–sun |

Upper = chest, back, shoulders, biceps, triceps; Lower = quadriceps, hamstrings, glutes, calves, core; Push = chest, shoulders, triceps; Pull = back, biceps, core; Legs = quadriceps, hamstrings, glutes, calves, core; Full Body = all required. Only required groups are used; a group in no session is added to the session with the fewest groups. The session name is stored in `training_session.session_name`.

**4.6 Choosing exercises.** Sort a group's eligible exercises by `is_compound DESC, difficulty_level DESC, id`. Each session gets one exercise per group; target count beginner 5, intermediate 6, advanced 7, never fewer than its groups. Extra slots go to second exercises in priority quadriceps, back, chest, hamstrings, glutes, shoulders, biceps, triceps, core, calves. The k-th occurrence of a group (k from 0) starts at index `(k × picks) mod n`, cyclically. Over 8 exercises: one set fewer each (min 2). Order: compound first, then larger groups. `planned_weight` stays NULL until 6.4.

**4.7 Sets, reps, rest.**

| Goal | Compound (sets × reps, rest s) | Isolation |
| --- | --- | --- |
| strength | 5 × 5, 180 | 3 × 8, 90 |
| muscle_gain | 4 × 8, 120 | 3 × 12, 75 |
| weight_loss | 3 × 12, 60 | 3 × 15, 45 |
| maintenance | 3 × 10, 90 | 2 × 12, 60 |
| general_fitness | 3 × 10, 75 | 2 × 12, 60 |
| endurance | 3 × 15, 45 | 2 × 20, 30 |

Beginners: one set fewer (min 2). `estimated_duration` = `600 s + Σ sets × (45 s + rest)`, rounded up to 5 min.

**4.8 Lifecycle (FR-P7).** Generate creates a `draft` (replaces the previous draft) named `"<Goal>, <n> day(s) per week"`. Accept: only a draft (else 409); sets `active`, `start_date` (given or today), `end_date`; archives the old active plan. Regenerate = generate again.

**4.9 Swap (FR-A1).** Alternatives: eligible exercises (4.2, 4.3) with the same primary group, not the current one and not already in the session, ordered compound first, then name. With `session_exercise_id` the plan's level and equipment snapshot is used (the same check as the swap); without it the profile (no profile: no level or equipment limit, injuries still apply). A swap keeps sets, reps, rest and weight and stores `original_exercise_id`; swapping back clears it. Rejected with 422 `invalid_swap`, `details[].code` one of `unknown_exercise`, `same_exercise`, `other_muscle_group`, `already_in_session`, `above_level`, `needs_equipment`, `excluded_by_injury`. Archived plans cannot be changed (409).

## 5. Diet plan (FR-P6, P7)

**5.1 Slots** (share of daily kcal and macros, default `planned_time`). The plan has 7 days (`meal.day_index` 1–7) and repeats from `start_date`: today's day = `((date − start_date) mod 7) + 1`.

| Meals | Slots |
| --- | --- |
| 3 | breakfast 0.30 08:00, lunch 0.40 13:00, dinner 0.30 19:00 |
| 4 | breakfast 0.25 08:00, lunch 0.35 13:00, snack 0.10 16:00, dinner 0.30 19:00 |
| 5 | breakfast 0.25 08:00, snack 0.10 10:30, lunch 0.30 13:30, snack 0.10 16:30, dinner 0.25 19:00 |

**5.2 Eligible food.** `is_active`; meal type in `suitable_meal_types`; diet type (vegetarian needs `is_vegetarian`, vegan needs `is_vegan`); no allergen of the user; not in `user_excluded_food`. The goal comes from the profile; `diet_type` from the request (default omnivore); `dietary_restrictions` is a free-text note that does not filter.

**5.3 Composition** (one item per role, by `food_item.diet_role`): breakfast = protein or dairy, carb, fruit, fat; lunch and dinner = protein, carb, vegetable, fat (a `dish` may replace protein + carb); snack = fruit or dairy, fat optional. For day `d` and slot `i`, take index `(d − 1 + 2i) mod n` of the role's items sorted by id; if it equals the same slot of the previous day and `n ≥ 2`, take the next.

**5.4 Grams.** Per meal, bounded least squares (`scipy.optimize.lsq_linear`) over grams/100 of each item, bounds `[min_portion_g, max_portion_g]`, minimising `Σ w_j ((Ax − t)_j / t_j)²` for kcal, protein, fat, carbs with weights 3, 2, 1, 1.5. Round to `portion_step_g` (bounds are multiples of it), clamp.

**5.5 Acceptance.** Each day within kcal ±5 %, protein ±10 %, fat ±15 %, carbs ±10 %. Stage 1: up to 5 attempts with the next indices. Stage 2, if stage 1 fails, up to 12 attempts: no `dish`; per meal the best of 8 consecutive rotation offsets (stop early within `GOOD_MEAL_ERROR` on every macro); each meal aims at its share of what the day still misses. Tolerances are never relaxed. Failure: 422 `insufficient_foods` with `{field: "food", code: "no_eligible_food", meal_type, role}` per unfillable role, otherwise `{code: "targets_not_reachable"}`. Name `"<Goal>[ <diet type>] diet, <n> meals"`. Lifecycle as 4.8.

## 6. Adaptation (FR-A2, A4, A5)

Runs when a workout with a `training_session_id` of a draft or active plan is saved. Changes go to `session_exercise` (next occurrence) and to `plan_adjustment`; a change that changes nothing is not recorded.

- **Reduce signal:** `workout_log.rpe_rating ≥ 9` (all logged exercises) or a set with `completed = false` (that exercise). When both hold, the reason is `reduce_high_rpe`.
- **Reserve signal:** every planned set completed with `reps ≥ planned_reps` and `weight ≥ planned_weight` (when set), and the highest set RPE (or the overall RPE when no set RPE) ≤ 7. No RPE at all: no signal.
- **No signal: nothing changes** (FR-A4).
- **Reduction** (wins over progression): weighted `max(min(round_to_2.5(w × 0.9), w − 2.5), 0)`; bodyweight or no planned weight: one set fewer (min 2).
- **Progression:** weighted `planned_weight + step` (2.5 kg upper and core, 5 kg lower); bodyweight reps + 1, max 20.
- **Baseline:** planned weight NULL and completed sets with weight > 0: `round_to_2.5(max weight × (0.9 if reduce signal else 1))`, reason `baseline`, nothing else in that step. Without such sets the exercise counts as having no planned weight (reduction = one set fewer).
- **Personal records:** completed sets with weight > 0 and reps ≤ 12; `e1RM = weight` for 1 rep, else `weight × (1 + reps/30)`. A higher e1RM than the current record creates a new record (old one `is_current = false`) and an `achievement` notification.

Vectors (planned 3 × 10):

| Case | Result (reason, sets, reps, kg) |
| --- | --- |
| A planned 60 upper, all 10 reps at 60, RPE 6 | progression, 3, 10, 62.5 |
| B planned 100 lower, all done at 100, RPE 7 | progression, 3, 10, 105.0 |
| C planned 60, overall RPE 9 | reduce_high_rpe, 3, 10, 55.0 |
| D planned 60, one set not completed, RPE 8 | reduce_incomplete_set, 3, 10, 55.0 |
| E all done, RPE 8 | no change |
| F all done, no RPE | no change |
| G weight NULL, sets 40, 42.5, 42.5 | baseline, 3, 10, 42.5 |
| H bodyweight, all done, RPE 6 | progression, 3, 11, – |
| I bodyweight, RPE 9 | reduce_high_rpe, 2, 10, – |
| J third set 9 reps | no change |
| K planned 60, all 10 reps at 55, RPE 6 | no change |

e1RM: 100 × 1 = 100; 100 × 5 = 116.67; 60 × 10 = 80.0.

## 7. Compliance (FR-R2)

- Workouts % = workouts done in the part of the period the active plan covers ÷ (sessions per week × covered days / 7) × 100; null without an active plan.
- Diet % = days from the active diet plan's start whose logged kcal are within ±10 % (inclusive) of the target ÷ days × 100; days without logs fail.

## 8. Analytics (FR-R1, R3, R5)

Windows in the user's time zone: `week` = today − 6 to today, `month` 30 days, `3months` 90 days. Report periods: Monday–Sunday = weekly, calendar month = monthly, else custom (max 366 days, not after today).

Metrics: weight change = last − first weigh-in (null with < 2); total workouts and average per week (total ÷ days/7); average calories over days with a log; tonnage = Σ reps × weight of completed sets with weight > 0; key lifts = three exercises with most workouts (then sets), first and best e1RM of sets with 1–12 reps. Chart series: weight per weigh-in, tonnage per workout day, calories per logged day, workouts per week and compliance per ISO week (dated Monday).

Minimum data (FR-R5): at least 7 distinct days with any record over the whole history, else `status: "insufficient_data"` and no series. A window without data gives null metrics and `key_lifts: []`.

## 9. Goal prediction (FR-R4)

Least-squares line of weight over days, weigh-ins of the last 28 days (today and the 27 days before), target = `user_profile.target_value`. R² of a flat series is 1.0; days to go are rounded half up.

| Situation | `status` |
| --- | --- |
| no target | `no_target` |
| < 3 weigh-ins or span < 7 days | `insufficient_data` |
| fitted weight within 0.5 kg of target | `goal_reached` |
| \|slope\| < 0.01 kg/day or > 730 days to go | `no_progress` |
| slope away from target | `moving_away` |
| otherwise | `ok`, `estimated_date` = last weigh-in + (target − fitted) ÷ slope |

Warnings: `low_fit` (R² < 0.5), `gaps` (gap > 10 days), `low_training_compliance` (workout compliance of the last 28 days < 60 %). `irregular_data` = any warning; a date is still returned.

Scenarios (tests use hand-computed fixtures with these outcomes; today 2026-10-14, target 78): −0.5 kg/week, 90 % compliance → ok, 2026-12-11, slope −0.49 kg/week, R² 1.0; scattered, 50 % → ok, 2027-02-21, −0.26, R² 0.18, `low_fit`, `low_training_compliance`; gaining with target 75 → `moving_away`; two weigh-ins → `insufficient_data`.

## 10. Meal suggestions (FR-N5)

`remaining` = targets of the active diet plan − today's logs. Remaining kcal < 100: no suggestions, `target_reached`. Otherwise:
1. Candidates: today's planned meals not yet logged (a log with that `planned_meal_id`) whose foods are all still allowed (5.2), plus every eligible food at a scaled portion.
2. Single food grams = clamp(`ideal_kcal` ÷ kcal per g, min, max) rounded to the step, `ideal_kcal = min(remaining kcal, 0.35 × daily target)`.
3. Drop candidates above `remaining kcal × 1.05`.
4. Score `Σ ((c_j − ideal_j) / ideal_j)²` over protein, fat, carbs (ideal = remaining macros scaled to `ideal_kcal`); best 5. `remaining` in the answer is shown as at least 0.

## 11. Recognition (FR-N1–N4)

`ai-service` returns up to K candidates `(label, confidence)`. Each label maps through `food_item.recognition_label` (no match: `food_item_id: null`, the user picks a food). Grams start at `default_portion_g`; nutrition = per 100 g × grams ÷ 100. Items get `low_confidence` and `allergy_warning` (shares an allergen with the user). `overall_confidence` = top candidate. Confirm writes `nutrition_log` (with `ai_confidence`, `ai_was_edited` = any item or grams changed, `meal_photo_url`) and its `nutrition_log_food_item` rows in one transaction, then deletes the Mongo document.

## 12. Weekly report (FR-R7, stretch)

A scheduler pass every 15 minutes creates, for each user past their local Monday 07:00, the weekly report of the previous Monday–Sunday if the minimum-data rule holds (insert-if-absent on the unique period key), and a `progress_update` notification with `data = {"report_id": …}` that the push job delivers.

-- TEMPORARY development seed: muscle groups, exercises and injury types.
--
-- Lets the training plan generator (B-11) run end to end before the real seeds of
-- DB-02 (muscle groups, injury types) and DB-03 (exercises) exist. Delete this file
-- and the rows it inserted when they are merged. Group names follow algorithms.md 3.
-- Every group has a beginner exercise without equipment, so every goal, level and
-- equipment tier gets a plan. Idempotent: rows are keyed by name.
--
-- Load: docker exec -i fitplan-postgres psql -U fitplan -d fitplan < database/dev/temporary_training_seed.sql

BEGIN;

INSERT INTO muscle_group (group_name, region, description) VALUES
  ('chest', 'upper', 'Temporary seed'),
  ('back', 'upper', 'Temporary seed'),
  ('shoulders', 'upper', 'Temporary seed'),
  ('biceps', 'upper', 'Temporary seed'),
  ('triceps', 'upper', 'Temporary seed'),
  ('quadriceps', 'lower', 'Temporary seed'),
  ('hamstrings', 'lower', 'Temporary seed'),
  ('glutes', 'lower', 'Temporary seed'),
  ('calves', 'lower', 'Temporary seed'),
  ('core', 'core', 'Temporary seed')
ON CONFLICT (group_name) DO NOTHING;

INSERT INTO exercise (name, difficulty_level, equipment, is_compound, is_bodyweight, description, instruction) VALUES
  ('Push-up', 'beginner', 'none', true, true, 'Temporary seed', 'Temporary seed'),
  ('Dumbbell bench press', 'beginner', 'home', true, false, 'Temporary seed', 'Temporary seed'),
  ('Barbell bench press', 'intermediate', 'gym', true, false, 'Temporary seed', 'Temporary seed'),
  ('Cable fly', 'intermediate', 'gym', false, false, 'Temporary seed', 'Temporary seed'),
  ('Decline push-up', 'advanced', 'none', true, true, 'Temporary seed', 'Temporary seed'),
  ('Inverted row under a table', 'beginner', 'none', true, true, 'Temporary seed', 'Temporary seed'),
  ('One-arm dumbbell row', 'beginner', 'home', true, false, 'Temporary seed', 'Temporary seed'),
  ('Pull-up', 'intermediate', 'home', true, true, 'Temporary seed', 'Temporary seed'),
  ('Lat pulldown', 'beginner', 'gym', true, false, 'Temporary seed', 'Temporary seed'),
  ('Barbell row', 'intermediate', 'gym', true, false, 'Temporary seed', 'Temporary seed'),
  ('Pike push-up', 'beginner', 'none', true, true, 'Temporary seed', 'Temporary seed'),
  ('Dumbbell shoulder press', 'beginner', 'home', true, false, 'Temporary seed', 'Temporary seed'),
  ('Lateral raise', 'beginner', 'home', false, false, 'Temporary seed', 'Temporary seed'),
  ('Barbell overhead press', 'intermediate', 'gym', true, false, 'Temporary seed', 'Temporary seed'),
  ('Towel curl', 'beginner', 'none', false, true, 'Temporary seed', 'Temporary seed'),
  ('Dumbbell curl', 'beginner', 'home', false, false, 'Temporary seed', 'Temporary seed'),
  ('Chin-up', 'intermediate', 'home', true, true, 'Temporary seed', 'Temporary seed'),
  ('Cable curl', 'beginner', 'gym', false, false, 'Temporary seed', 'Temporary seed'),
  ('Chair dip', 'beginner', 'none', true, true, 'Temporary seed', 'Temporary seed'),
  ('Overhead dumbbell extension', 'beginner', 'home', false, false, 'Temporary seed', 'Temporary seed'),
  ('Cable pushdown', 'beginner', 'gym', false, false, 'Temporary seed', 'Temporary seed'),
  ('Close-grip bench press', 'intermediate', 'gym', true, false, 'Temporary seed', 'Temporary seed'),
  ('Bodyweight squat', 'beginner', 'none', true, true, 'Temporary seed', 'Temporary seed'),
  ('Goblet squat', 'beginner', 'home', true, false, 'Temporary seed', 'Temporary seed'),
  ('Bulgarian split squat', 'intermediate', 'home', true, false, 'Temporary seed', 'Temporary seed'),
  ('Barbell back squat', 'intermediate', 'gym', true, false, 'Temporary seed', 'Temporary seed'),
  ('Leg extension', 'beginner', 'gym', false, false, 'Temporary seed', 'Temporary seed'),
  ('Single-leg hip hinge', 'beginner', 'none', true, true, 'Temporary seed', 'Temporary seed'),
  ('Dumbbell Romanian deadlift', 'beginner', 'home', true, false, 'Temporary seed', 'Temporary seed'),
  ('Nordic curl', 'advanced', 'none', false, true, 'Temporary seed', 'Temporary seed'),
  ('Lying leg curl', 'beginner', 'gym', false, false, 'Temporary seed', 'Temporary seed'),
  ('Barbell Romanian deadlift', 'intermediate', 'gym', true, false, 'Temporary seed', 'Temporary seed'),
  ('Glute bridge', 'beginner', 'none', true, true, 'Temporary seed', 'Temporary seed'),
  ('Dumbbell hip thrust', 'beginner', 'home', true, false, 'Temporary seed', 'Temporary seed'),
  ('Barbell hip thrust', 'intermediate', 'gym', true, false, 'Temporary seed', 'Temporary seed'),
  ('Cable kickback', 'beginner', 'gym', false, false, 'Temporary seed', 'Temporary seed'),
  ('Standing calf raise', 'beginner', 'none', false, true, 'Temporary seed', 'Temporary seed'),
  ('Single-leg dumbbell calf raise', 'beginner', 'home', false, false, 'Temporary seed', 'Temporary seed'),
  ('Seated calf raise machine', 'beginner', 'gym', false, false, 'Temporary seed', 'Temporary seed'),
  ('Plank', 'beginner', 'none', false, true, 'Temporary seed', 'Temporary seed'),
  ('Dead bug', 'beginner', 'none', false, true, 'Temporary seed', 'Temporary seed'),
  ('Hanging knee raise', 'intermediate', 'home', false, true, 'Temporary seed', 'Temporary seed'),
  ('Cable crunch', 'beginner', 'gym', false, false, 'Temporary seed', 'Temporary seed'),
  ('Ab wheel rollout', 'advanced', 'home', true, true, 'Temporary seed', 'Temporary seed')
ON CONFLICT (name) DO NOTHING;

INSERT INTO exercise_muscle_group (exercise_id, muscle_group_id, is_primary)
SELECT e.id, m.id, v.is_primary FROM (VALUES
  ('Push-up', 'chest', true),
  ('Push-up', 'triceps', false),
  ('Push-up', 'shoulders', false),
  ('Dumbbell bench press', 'chest', true),
  ('Dumbbell bench press', 'triceps', false),
  ('Barbell bench press', 'chest', true),
  ('Barbell bench press', 'triceps', false),
  ('Barbell bench press', 'shoulders', false),
  ('Cable fly', 'chest', true),
  ('Decline push-up', 'chest', true),
  ('Decline push-up', 'triceps', false),
  ('Inverted row under a table', 'back', true),
  ('Inverted row under a table', 'biceps', false),
  ('One-arm dumbbell row', 'back', true),
  ('One-arm dumbbell row', 'biceps', false),
  ('Pull-up', 'back', true),
  ('Pull-up', 'biceps', false),
  ('Lat pulldown', 'back', true),
  ('Lat pulldown', 'biceps', false),
  ('Barbell row', 'back', true),
  ('Barbell row', 'biceps', false),
  ('Barbell row', 'core', false),
  ('Pike push-up', 'shoulders', true),
  ('Pike push-up', 'triceps', false),
  ('Dumbbell shoulder press', 'shoulders', true),
  ('Dumbbell shoulder press', 'triceps', false),
  ('Lateral raise', 'shoulders', true),
  ('Barbell overhead press', 'shoulders', true),
  ('Barbell overhead press', 'triceps', false),
  ('Barbell overhead press', 'core', false),
  ('Towel curl', 'biceps', true),
  ('Dumbbell curl', 'biceps', true),
  ('Chin-up', 'biceps', true),
  ('Chin-up', 'back', false),
  ('Cable curl', 'biceps', true),
  ('Chair dip', 'triceps', true),
  ('Chair dip', 'chest', false),
  ('Overhead dumbbell extension', 'triceps', true),
  ('Cable pushdown', 'triceps', true),
  ('Close-grip bench press', 'triceps', true),
  ('Close-grip bench press', 'chest', false),
  ('Bodyweight squat', 'quadriceps', true),
  ('Bodyweight squat', 'glutes', false),
  ('Goblet squat', 'quadriceps', true),
  ('Goblet squat', 'glutes', false),
  ('Bulgarian split squat', 'quadriceps', true),
  ('Bulgarian split squat', 'glutes', false),
  ('Barbell back squat', 'quadriceps', true),
  ('Barbell back squat', 'glutes', false),
  ('Barbell back squat', 'core', false),
  ('Leg extension', 'quadriceps', true),
  ('Single-leg hip hinge', 'hamstrings', true),
  ('Single-leg hip hinge', 'glutes', false),
  ('Dumbbell Romanian deadlift', 'hamstrings', true),
  ('Dumbbell Romanian deadlift', 'glutes', false),
  ('Nordic curl', 'hamstrings', true),
  ('Lying leg curl', 'hamstrings', true),
  ('Barbell Romanian deadlift', 'hamstrings', true),
  ('Barbell Romanian deadlift', 'glutes', false),
  ('Barbell Romanian deadlift', 'back', false),
  ('Glute bridge', 'glutes', true),
  ('Glute bridge', 'hamstrings', false),
  ('Dumbbell hip thrust', 'glutes', true),
  ('Dumbbell hip thrust', 'hamstrings', false),
  ('Barbell hip thrust', 'glutes', true),
  ('Barbell hip thrust', 'hamstrings', false),
  ('Cable kickback', 'glutes', true),
  ('Standing calf raise', 'calves', true),
  ('Single-leg dumbbell calf raise', 'calves', true),
  ('Seated calf raise machine', 'calves', true),
  ('Plank', 'core', true),
  ('Dead bug', 'core', true),
  ('Hanging knee raise', 'core', true),
  ('Cable crunch', 'core', true),
  ('Ab wheel rollout', 'core', true),
  ('Ab wheel rollout', 'shoulders', false)
) AS v(exercise, muscle_group, is_primary)
JOIN exercise e ON e.name = v.exercise
JOIN muscle_group m ON m.group_name = v.muscle_group
ON CONFLICT DO NOTHING;

INSERT INTO injury_type (type_name, description, avg_healing_time_days) VALUES
  ('Shoulder strain', 'Overuse or minor tear of the shoulder muscles', 21),
  ('Lower back strain', 'Strained lower back muscles', 14),
  ('Knee pain', 'Non-acute pain around the knee', 28)
ON CONFLICT (type_name) DO NOTHING;

INSERT INTO injury_type_excluded_exercise (injury_type_id, exercise_id)
SELECT t.id, e.id FROM (VALUES
  ('Shoulder strain', 'Barbell overhead press'),
  ('Shoulder strain', 'Pike push-up'),
  ('Lower back strain', 'Barbell back squat'),
  ('Lower back strain', 'Barbell row'),
  ('Lower back strain', 'Barbell Romanian deadlift'),
  ('Knee pain', 'Bulgarian split squat'),
  ('Knee pain', 'Barbell back squat')
) AS v(injury_type, exercise)
JOIN injury_type t ON t.type_name = v.injury_type
JOIN exercise e ON e.name = v.exercise
ON CONFLICT DO NOTHING;

COMMIT;

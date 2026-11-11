import type { TrainingSession } from '@/training/training-api';
import {
  countNotDone,
  describeAdjustment,
  extraSet,
  initialDrafts,
  toWorkoutInput,
  validateSets,
} from '@/workout/workout-form';

const session: TrainingSession = {
  id: 11,
  session_order: 1,
  session_name: 'Full Body A',
  day_of_week: 1,
  estimated_duration: 50,
  exercises: [
    {
      id: 102,
      exercise_id: 6,
      exercise_name: 'Push-up',
      sort_order: 2,
      planned_sets: 2,
      planned_reps: 12,
      planned_weight: null,
      rest_seconds: 60,
    },
    {
      id: 101,
      exercise_id: 5,
      exercise_name: 'Barbell back squat',
      sort_order: 1,
      planned_sets: 3,
      planned_reps: 10,
      planned_weight: 60,
      rest_seconds: 120,
    },
  ],
};

describe('workout form', () => {
  it('starts from the planned sets in plan order', () => {
    const drafts = initialDrafts(session);
    expect(drafts.map((d) => d.exercise.exercise_name)).toEqual(['Barbell back squat', 'Push-up']);
    expect(drafts[0].sets).toHaveLength(3);
    expect(drafts[0].sets[0]).toEqual({ reps: '10', weight: '60', rpe: '', done: false });
    expect(drafts[1].sets[0].weight).toBe('');
    expect(extraSet(drafts[0].sets[2])).toEqual({ reps: '10', weight: '60', rpe: '', done: false });
  });

  it('rejects reps that are not whole numbers, a weight over 999.99 and an RPE outside 1–10', () => {
    const drafts = initialDrafts(session);
    drafts[0].sets[0] = { reps: '8.5', weight: '1000', rpe: '11', done: true };
    drafts[1].sets[0] = { reps: '12', weight: '', rpe: '', done: true };
    expect(validateSets(drafts)).toEqual({ '0.0.reps': 'Whole number', '0.0.weight': '0–999.99', '0.0.rpe': '1–10' });
  });

  it('sends unticked sets as not completed and an empty weight as bodyweight', () => {
    const drafts = initialDrafts(session);
    drafts[0].sets = drafts[0].sets.map((set) => ({ ...set, done: true }));
    drafts[0].sets[2] = { reps: '8', weight: '62,5', rpe: '9', done: true };
    drafts[1].sets[0].done = true;
    expect(countNotDone(drafts)).toBe(1);

    const input = toWorkoutInput({ clientUuid: 'uuid-1', sessionId: 11, logDate: '2026-11-10', rpe: 8, drafts });
    expect(input).toMatchObject({ client_uuid: 'uuid-1', training_session_id: 11, log_date: '2026-11-10', rpe_rating: 8 });
    expect(input.exercises[0]).toMatchObject({ exercise_id: 5, session_exercise_id: 101, sort_order: 1 });
    expect(input.exercises[0].sets[2]).toEqual({ set_number: 3, reps: 8, weight: 62.5, completed: true, rpe: 9 });
    expect(input.exercises[1].sets).toEqual([
      { set_number: 1, reps: 12, weight: 0, completed: true, rpe: null },
      { set_number: 2, reps: 12, weight: 0, completed: false, rpe: null },
    ]);
  });

  // Vectors A, G, I and D of algorithms.md 6
  it('describes plan adjustments', () => {
    expect(
      describeAdjustment({ session_exercise_id: 1, reason: 'progression', old_sets: 3, new_sets: 3, old_reps: 10, new_reps: 10, old_weight: 60, new_weight: 62.5 }),
    ).toEqual({ reason: 'You had strength left, so the next workout is a little harder', change: '60 → 62.5 kg' });
    expect(describeAdjustment({ session_exercise_id: 1, reason: 'baseline', old_weight: null, new_weight: 42.5 }).change).toBe(
      '42.5 kg',
    );
    expect(
      describeAdjustment({ session_exercise_id: 1, reason: 'reduce_high_rpe', old_sets: 3, new_sets: 2, old_weight: null, new_weight: null }),
    ).toEqual({ reason: 'The workout felt very hard (RPE 9 or more), so the next one is lighter', change: '3 → 2 sets' });
    expect(
      describeAdjustment({ session_exercise_id: 1, reason: 'reduce_incomplete_set', old_weight: 60, new_weight: 55 }).reason,
    ).toBe('A set was not completed, so the next workout is lighter');
  });
});

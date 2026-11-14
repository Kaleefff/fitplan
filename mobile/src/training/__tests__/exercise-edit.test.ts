import { changesOf, toEditForm, validateEdit } from '@/training/exercise-edit';
import type { SessionExercise } from '@/training/training-api';

const exercise = (extra: Partial<SessionExercise> = {}) =>
  ({
    id: 101,
    exercise_id: 5,
    exercise_name: 'Barbell back squat',
    sort_order: 1,
    planned_sets: 3,
    planned_reps: 10,
    planned_weight: 60,
    rest_seconds: 120,
    ...extra,
  }) as SessionExercise;

describe('exercise edit form', () => {
  it('starts with the planned values', () => {
    expect(toEditForm(exercise())).toEqual({ sets: '3', reps: '10', weight: '60', rest: '120' });
    expect(toEditForm(exercise({ planned_weight: null })).weight).toBe('');
  });

  it('checks the limits of PATCH /session-exercises', () => {
    const ok = { sets: '3', reps: '10', weight: '60', rest: '120' };
    expect(validateEdit(ok, exercise())).toEqual({});
    expect(validateEdit({ ...ok, sets: '0', reps: '2.5', rest: '-1' }, exercise())).toEqual({
      sets: 'Enter a number from 1 to 32767.',
      reps: 'Enter a whole number.',
      rest: 'Enter a whole number.',
    });
    expect(validateEdit({ ...ok, rest: '0', weight: '0' }, exercise())).toEqual({});
    expect(validateEdit({ ...ok, weight: '999.99' }, exercise())).toEqual({});
    expect(validateEdit({ ...ok, weight: '1000' }, exercise()).weight).toBeDefined();
    expect(validateEdit({ ...ok, weight: '62.555' }, exercise()).weight).toBeDefined();
  });

  it('allows no weight only while the plan has none', () => {
    const form = { sets: '3', reps: '10', weight: ' ', rest: '120' };
    expect(validateEdit(form, exercise({ planned_weight: null }))).toEqual({});
    expect(validateEdit(form, exercise()).weight).toBe('Enter the weight in kg (0 for body weight).');
  });

  it('sends only what changed', () => {
    expect(changesOf(exercise(), toEditForm(exercise()))).toEqual({});
    expect(changesOf(exercise(), { sets: '4', reps: '10', weight: '62,5', rest: '90' })).toEqual({
      planned_sets: 4,
      planned_weight: 62.5,
      rest_seconds: 90,
    });
    expect(changesOf(exercise({ planned_weight: null }), { sets: '3', reps: '8', weight: '', rest: '120' })).toEqual({
      planned_reps: 8,
    });
  });
});

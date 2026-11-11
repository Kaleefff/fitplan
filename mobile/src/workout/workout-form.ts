import type { components } from '@/api/schema';
import { parseNumber } from '@/profile/validation';
import type { TrainingSession } from '@/training/training-api';

type Schemas = components['schemas'];
export type WorkoutInput = Schemas['WorkoutInput'];
export type WorkoutResult = Schemas['WorkoutResult'];
export type PlanAdjustment = Schemas['PlanAdjustment'];
export type SessionExercise = TrainingSession['exercises'][number];

/** One set while the user types: numbers stay text until they are checked */
export type SetDraft = { reps: string; weight: string; rpe: string; done: boolean };
export type ExerciseDraft = { exercise: SessionExercise; sets: SetDraft[] };

/** The planned sets, filled in with the planned reps and weight */
export function initialDrafts(session: TrainingSession): ExerciseDraft[] {
  return [...session.exercises]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((exercise) => ({
      exercise,
      sets: Array.from({ length: exercise.planned_sets }, () => ({
        reps: String(exercise.planned_reps),
        weight: exercise.planned_weight === null ? '' : String(exercise.planned_weight),
        rpe: '',
        done: false,
      })),
    }));
}

/** An extra set copies the reps and weight of the last one */
export function extraSet(last: SetDraft | undefined): SetDraft {
  return { reps: last?.reps ?? '', weight: last?.weight ?? '', rpe: '', done: false };
}

/** Key of a field error: "<exercise index>.<set index>.<field>" */
export const fieldKey = (exercise: number, set: number, field: 'reps' | 'weight' | 'rpe') =>
  `${exercise}.${set}.${field}`;

// workout_set.weight is numeric(5,2), as the weight of a planned exercise (0–999.99)
const MAX_WEIGHT = 999.99;

export function validateSets(drafts: ExerciseDraft[]): Record<string, string> {
  const errors: Record<string, string> = {};
  drafts.forEach((draft, e) =>
    draft.sets.forEach((set, s) => {
      const reps = parseNumber(set.reps);
      if (reps === null || !Number.isInteger(reps)) {
        errors[fieldKey(e, s, 'reps')] = 'Whole number';
      }
      // Empty weight means bodyweight (0 kg)
      const weight = set.weight.trim() ? parseNumber(set.weight) : 0;
      if (weight === null || weight > MAX_WEIGHT) {
        errors[fieldKey(e, s, 'weight')] = '0–999.99';
      }
      const rpe = set.rpe.trim() ? parseNumber(set.rpe) : 1;
      if (rpe === null || !Number.isInteger(rpe) || rpe < 1 || rpe > 10) {
        errors[fieldKey(e, s, 'rpe')] = '1–10';
      }
    }),
  );
  return errors;
}

export function countNotDone(drafts: ExerciseDraft[]): number {
  return drafts.reduce((sum, draft) => sum + draft.sets.filter((set) => !set.done).length, 0);
}

type WorkoutParams = {
  clientUuid: string;
  sessionId: number;
  logDate: string;
  rpe: number;
  drafts: ExerciseDraft[];
};

/** The request body; call only after validateSets found no errors */
export function toWorkoutInput({ clientUuid, sessionId, logDate, rpe, drafts }: WorkoutParams): WorkoutInput {
  return {
    client_uuid: clientUuid,
    training_session_id: sessionId,
    log_date: logDate,
    rpe_rating: rpe,
    exercises: drafts.map((draft, e) => ({
      exercise_id: draft.exercise.exercise_id,
      session_exercise_id: draft.exercise.id,
      sort_order: e + 1,
      sets: draft.sets.map((set, s) => ({
        set_number: s + 1,
        reps: Number(parseNumber(set.reps)),
        weight: set.weight.trim() ? Math.round(Number(parseNumber(set.weight)) * 100) / 100 : 0,
        // A set not marked as done counts as not completed (algorithms.md 6, reduce signal)
        completed: set.done,
        rpe: set.rpe.trim() ? Number(parseNumber(set.rpe)) : null,
      })),
    })),
  };
}

// Why the plan changed, in the words of algorithms.md 6
const REASONS: Record<PlanAdjustment['reason'], string> = {
  baseline: 'Starting weight taken from this workout',
  progression: 'You had strength left, so the next workout is a little harder',
  reduce_high_rpe: 'The workout felt very hard (RPE 9 or more), so the next one is lighter',
  reduce_incomplete_set: 'A set was not completed, so the next workout is lighter',
};

/** Reason and change of one adjustment, e.g. "60 → 62.5 kg" */
export function describeAdjustment(adjustment: PlanAdjustment): { reason: string; change: string } {
  const changes: string[] = [];
  const { old_sets, new_sets, old_reps, new_reps, old_weight, new_weight } = adjustment;
  if (old_sets !== undefined && new_sets !== undefined && old_sets !== new_sets) {
    changes.push(`${old_sets} → ${new_sets} sets`);
  }
  if (old_reps !== undefined && new_reps !== undefined && old_reps !== new_reps) {
    changes.push(`${old_reps} → ${new_reps} reps`);
  }
  if (new_weight !== undefined && new_weight !== null && old_weight !== new_weight) {
    changes.push(old_weight === null || old_weight === undefined ? `${new_weight} kg` : `${old_weight} → ${new_weight} kg`);
  }
  return { reason: REASONS[adjustment.reason], change: changes.join(', ') };
}

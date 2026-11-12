import { parseNumber } from '@/profile/validation';
import type { SessionExercise, SessionExercisePatch } from '@/training/training-api';

/** The fields of a planned exercise while the user types: numbers stay text until they are checked */
export type EditForm = { sets: string; reps: string; weight: string; rest: string };
export type EditField = keyof EditForm;

// The limits of PATCH /session-exercises (api-rules.md: weight 0–999.99; the counts are smallint)
const MAX_COUNT = 32767;
const MAX_WEIGHT = 999.99;

export function toEditForm(exercise: SessionExercise): EditForm {
  return {
    sets: String(exercise.planned_sets),
    reps: String(exercise.planned_reps),
    weight: exercise.planned_weight === null ? '' : String(exercise.planned_weight),
    rest: String(exercise.rest_seconds),
  };
}

function checkWhole(text: string, min: number): string | undefined {
  const value = parseNumber(text);
  if (value === null || !Number.isInteger(value)) {
    return 'Enter a whole number.';
  }
  if (value < min || value > MAX_COUNT) {
    return `Enter a number from ${min} to ${MAX_COUNT}.`;
  }
  return undefined;
}

/** Field errors; an empty weight is allowed only while the plan has none (before the first workout) */
export function validateEdit(form: EditForm, exercise: SessionExercise): Partial<Record<EditField, string>> {
  const errors: Partial<Record<EditField, string>> = {
    sets: checkWhole(form.sets, 1),
    reps: checkWhole(form.reps, 1),
    rest: checkWhole(form.rest, 0),
  };
  if (form.weight.trim()) {
    const weight = parseNumber(form.weight);
    if (weight === null || weight > MAX_WEIGHT || !/^\d+([.,]\d{1,2})?$/.test(form.weight.trim())) {
      errors.weight = `Enter a weight from 0 to ${MAX_WEIGHT} kg, at most 2 decimals.`;
    }
  } else if (exercise.planned_weight !== null) {
    errors.weight = 'Enter the weight in kg (0 for body weight).';
  }
  return Object.fromEntries(Object.entries(errors).filter(([, error]) => error)) as Partial<
    Record<EditField, string>
  >;
}

/** Only the fields that differ from the plan, as PATCH takes them; call after validateEdit */
export function changesOf(exercise: SessionExercise, form: EditForm): SessionExercisePatch {
  const changes: SessionExercisePatch = {};
  const sets = parseNumber(form.sets)!;
  const reps = parseNumber(form.reps)!;
  const rest = parseNumber(form.rest)!;
  const weight = form.weight.trim() ? parseNumber(form.weight) : null;
  if (sets !== exercise.planned_sets) changes.planned_sets = sets;
  if (reps !== exercise.planned_reps) changes.planned_reps = reps;
  if (rest !== exercise.rest_seconds) changes.rest_seconds = rest;
  if (weight !== null && weight !== exercise.planned_weight) changes.planned_weight = weight;
  return changes;
}

/**
 * Why the user wants to change an exercise. The reason is not sent to the server (the contract has
 * no field for it); it points the user to the change that fits it.
 */
export type ChangeReason = 'too_hard' | 'too_easy' | 'pain' | 'no_equipment';

export const REASON_OPTIONS: { value: ChangeReason; label: string }[] = [
  { value: 'too_hard', label: 'Too hard' },
  { value: 'too_easy', label: 'Too easy' },
  { value: 'pain', label: 'It hurts' },
  { value: 'no_equipment', label: 'No equipment' },
];

export const REASON_ADVICE: Record<ChangeReason, string> = {
  too_hard: 'Lower the weight, the reps or the sets below, or swap it for another exercise.',
  too_easy: 'Raise the weight or the reps below.',
  pain:
    'Stop this exercise and swap it for another one. Add the injury to your profile, so new plans leave ' +
    'out what hurts. If the pain stays, see a doctor.',
  no_equipment: 'Swap it for an exercise you can do with what you have.',
};

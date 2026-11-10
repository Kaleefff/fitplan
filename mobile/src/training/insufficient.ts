import type { ApiError } from '@/api/errors';
import type { components } from '@/api/schema';

type Goal = components['schemas']['Goal'];
type Equipment = components['schemas']['Equipment'];

/** What a 422 `insufficient_exercises` answer says (algorithms.md 4.4) */
export type InsufficientExercises = {
  /** Required groups without an eligible exercise; empty when injuries skip every group */
  groups: string[];
  /** The lowest higher equipment tier that covers every group */
  equipment: Equipment | null;
  /** Goals fully covered with the current settings */
  goals: Goal[];
};

export function readInsufficientExercises(error: ApiError): InsufficientExercises | null {
  if (error.code !== 'insufficient_exercises') {
    return null;
  }
  const result: InsufficientExercises = { groups: [], equipment: null, goals: [] };
  for (const detail of error.details as Record<string, unknown>[]) {
    if (detail.code === 'no_eligible_exercise' && typeof detail.muscle_group === 'string') {
      result.groups.push(detail.muscle_group);
    } else if (detail.code === 'change_equipment' && typeof detail.equipment === 'string') {
      result.equipment = detail.equipment as Equipment;
    } else if (detail.code === 'change_goal' && Array.isArray(detail.goals)) {
      result.goals = detail.goals as Goal[];
    }
  }
  return result;
}

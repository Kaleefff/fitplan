import { api, unwrap } from '@/api/client';
import type { WorkoutInput, WorkoutResult } from '@/workout/workout-form';

/** Saves the workout; the plan adapts and the changes come back (FR-A2, A4, A5) */
export function logWorkout(input: WorkoutInput): Promise<WorkoutResult> {
  return unwrap(api.POST('/workouts', { body: input }));
}

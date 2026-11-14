import { api, unwrap } from '@/api/client';
import { ApiError } from '@/api/errors';
import type { components } from '@/api/schema';
import { capitalize, EQUIPMENT_OPTIONS, labelOf, LEVEL_OPTIONS } from '@/profile/options';

export type Exercise = components['schemas']['Exercise'];

/** null when the exercise is not in the library */
export async function getExercise(exerciseId: number): Promise<Exercise | null> {
  try {
    return await unwrap(api.GET('/exercises/{exercise_id}', { params: { path: { exercise_id: exerciseId } } }));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** The text instruction as steps, one sentence each (FR-P8) */
export function instructionSteps(instruction: string): string[] {
  const sentences = instruction.match(/[^.!?]+[.!?]+/g) ?? [];
  const steps = sentences.map((sentence) => sentence.trim()).filter(Boolean);
  // Text after the last full stop is a step of its own
  const rest = instruction.replace(/[^.!?]+[.!?]+/g, '').trim();
  return rest ? [...steps, rest] : steps;
}

/** "Beginner · Gym equipment · Compound" */
export function exerciseTags(exercise: Exercise): string {
  return [
    labelOf(LEVEL_OPTIONS, exercise.difficulty_level),
    exercise.is_bodyweight ? 'Body weight' : `${labelOf(EQUIPMENT_OPTIONS, exercise.equipment)} equipment`,
    exercise.is_compound ? 'Compound' : 'Isolation',
  ].join(' · ');
}

/** The main muscle group and the others the exercise also works */
export function musclesOf(exercise: Exercise): { main: string[]; also: string[] } {
  const name = (group: Exercise['muscle_groups'][number]) => capitalize(group.group_name);
  return {
    main: exercise.muscle_groups.filter((g) => g.is_primary).map(name),
    also: exercise.muscle_groups.filter((g) => !g.is_primary).map(name),
  };
}

import { ApiError } from '@/api/errors';
import { exerciseTags, getExercise, instructionSteps, musclesOf, type Exercise } from '@/exercises/exercise-api';

const mockGet = jest.fn();
jest.mock('@/api/client', () => ({
  api: { GET: (...args: unknown[]) => mockGet(...args) },
  unwrap: (call: Promise<unknown>) => call,
}));

const press: Exercise = {
  id: 7,
  name: 'Barbell bench press',
  difficulty_level: 'intermediate',
  equipment: 'gym',
  is_compound: true,
  is_bodyweight: false,
  description: 'Horizontal press with a barbell.',
  instruction:
    'Lie with eyes under the bar, feet flat and shoulder blades pulled back. Lower the bar to the lower chest ' +
    'with control, then press it back up over the shoulders. Use a spotter or safety arms.',
  muscle_groups: [
    { muscle_group_id: 3, group_name: 'triceps', is_primary: false },
    { muscle_group_id: 1, group_name: 'chest', is_primary: true },
    { muscle_group_id: 4, group_name: 'shoulders', is_primary: false },
  ],
};

describe('exercise details (FR-P8)', () => {
  it('splits the text instruction into steps', () => {
    expect(instructionSteps(press.instruction)).toEqual([
      'Lie with eyes under the bar, feet flat and shoulder blades pulled back.',
      'Lower the bar to the lower chest with control, then press it back up over the shoulders.',
      'Use a spotter or safety arms.',
    ]);
    expect(instructionSteps('Keep the back straight! Breathe out on the way up')).toEqual([
      'Keep the back straight!',
      'Breathe out on the way up',
    ]);
    expect(instructionSteps('')).toEqual([]);
  });

  it('describes level, equipment and kind', () => {
    expect(exerciseTags(press)).toBe('Intermediate · Gym equipment · Compound');
    expect(exerciseTags({ ...press, is_bodyweight: true, is_compound: false, difficulty_level: 'beginner' })).toBe(
      'Beginner · Body weight · Isolation',
    );
  });

  it('separates the main muscle group from the others', () => {
    expect(musclesOf(press)).toEqual({ main: ['Chest'], also: ['Triceps', 'Shoulders'] });
  });

  it('gets one exercise, null when it is not in the library', async () => {
    mockGet.mockResolvedValueOnce(press);
    expect(await getExercise(7)).toBe(press);
    expect(mockGet).toHaveBeenCalledWith('/exercises/{exercise_id}', { params: { path: { exercise_id: 7 } } });

    mockGet.mockRejectedValueOnce(new ApiError(404, 'not_found', 'Not found', []));
    expect(await getExercise(999)).toBeNull();
  });
});

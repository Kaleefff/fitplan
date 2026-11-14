import { fireEvent, screen } from '@testing-library/react-native';

import { ApiError } from '@/api/errors';
import ExerciseScreen from '@/app/exercise/[id]';
import type { Exercise } from '@/exercises/exercise-api';
import { renderWithTheme } from '@/test-utils';

let mockParams: { id?: string } = {};
jest.mock('expo-router', () => ({
  router: { back: jest.fn() },
  useLocalSearchParams: () => mockParams,
}));

const mockGetExercise = jest.fn();
jest.mock('@/exercises/exercise-api', () => ({
  ...jest.requireActual('@/exercises/exercise-api'),
  getExercise: (...args: unknown[]) => mockGetExercise(...args),
}));

const squat: Exercise = {
  id: 5,
  name: 'Barbell back squat',
  difficulty_level: 'intermediate',
  equipment: 'gym',
  is_compound: true,
  is_bodyweight: false,
  description: 'The main lower-body strength lift.',
  instruction: 'Set the bar on the upper back. Sit down between the heels until the thighs are level. Stand up.',
  muscle_groups: [
    { muscle_group_id: 6, group_name: 'quadriceps', is_primary: true },
    { muscle_group_id: 8, group_name: 'glutes', is_primary: false },
  ],
};

describe('ExerciseScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockParams = { id: '5' };
  });

  it('shows what the exercise is, the steps and the muscles (FR-P8)', async () => {
    mockGetExercise.mockResolvedValue(squat);
    await renderWithTheme(<ExerciseScreen />);

    expect(await screen.findByText('Barbell back squat')).toBeOnTheScreen();
    expect(mockGetExercise).toHaveBeenCalledWith(5);
    expect(screen.getByText('Intermediate · Gym equipment · Compound')).toBeOnTheScreen();
    expect(screen.getByText('The main lower-body strength lift.')).toBeOnTheScreen();
    expect(screen.getByLabelText('Step 1. Set the bar on the upper back.')).toBeOnTheScreen();
    expect(screen.getByLabelText('Step 3. Stand up.')).toBeOnTheScreen();
    expect(screen.getByText('Main: Quadriceps')).toBeOnTheScreen();
    expect(screen.getByText('Also works: Glutes')).toBeOnTheScreen();
  });

  it('says when the exercise is not in the library', async () => {
    mockGetExercise.mockResolvedValue(null);
    await renderWithTheme(<ExerciseScreen />);

    expect(await screen.findByText('This exercise is not in the exercise library.')).toBeOnTheScreen();
  });

  it('does not ask the server for a wrong id', async () => {
    mockParams = { id: 'abc' };
    await renderWithTheme(<ExerciseScreen />);

    expect(screen.getByText('This exercise is not in the exercise library.')).toBeOnTheScreen();
    expect(mockGetExercise).not.toHaveBeenCalled();
  });

  it('tries again after a connection problem', async () => {
    mockGetExercise.mockRejectedValueOnce(new ApiError(0, 'network_error', 'offline', [])).mockResolvedValue(squat);
    await renderWithTheme(<ExerciseScreen />);

    await fireEvent.press(await screen.findByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Barbell back squat')).toBeOnTheScreen();
    expect(mockGetExercise).toHaveBeenCalledTimes(2);
  });
});

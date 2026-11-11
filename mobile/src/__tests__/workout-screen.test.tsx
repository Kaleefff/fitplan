import { fireEvent, screen } from '@testing-library/react-native';

import WorkoutScreen from '@/app/workout';
import { renderWithTheme } from '@/test-utils';
import type { TrainingPlan } from '@/training/training-api';

jest.mock('expo-crypto', () => ({ randomUUID: () => '1b4e28ba-2fa1-11d2-883f-0016d3cca427' }));
jest.mock('expo-router', () => ({
  router: { back: jest.fn() },
  useLocalSearchParams: () => ({ sessionId: '11' }),
}));

const mockLogWorkout = jest.fn();
jest.mock('@/workout/workout-api', () => ({ logWorkout: (...args: unknown[]) => mockLogWorkout(...args) }));

const activePlan: Partial<TrainingPlan> = {
  id: 1,
  status: 'active',
  sessions: [
    {
      id: 11,
      session_order: 1,
      session_name: 'Full Body A',
      day_of_week: 1,
      estimated_duration: 50,
      exercises: [
        {
          id: 101,
          exercise_id: 5,
          exercise_name: 'Barbell back squat',
          sort_order: 1,
          planned_sets: 2,
          planned_reps: 10,
          planned_weight: 60,
          rest_seconds: 120,
        },
      ],
    },
  ],
};
jest.mock('@/training/training-api', () => ({ getActivePlan: async () => activePlan }));

const tick = (name: string) => fireEvent.press(screen.getByRole('checkbox', { name }));

describe('WorkoutScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('logs the sets, starts the rest after a set and shows the plan change (M-13 Done)', async () => {
    mockLogWorkout.mockResolvedValue({
      workout: { id: 7 },
      adjustments: [
        {
          session_exercise_id: 101,
          reason: 'reduce_high_rpe',
          old_sets: 2,
          new_sets: 2,
          old_reps: 10,
          new_reps: 10,
          old_weight: 60,
          new_weight: 55,
        },
      ],
      new_personal_records: [{ id: 3, exercise_id: 5, max_weight: 60, max_reps: 10, achieved_date: '2026-11-10' }],
    });
    await renderWithTheme(<WorkoutScreen />);

    await tick('Barbell back squat, set 1, done');
    expect(screen.getByText('Rest 2:00')).toBeOnTheScreen();
    await fireEvent.changeText(screen.getByLabelText('Barbell back squat, set 2, reps'), '8');
    await tick('Barbell back squat, set 2, done');
    await fireEvent.press(screen.getByRole('radio', { name: '9' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Save workout' }));

    const input = mockLogWorkout.mock.calls[0][0];
    expect(input).toMatchObject({
      client_uuid: '1b4e28ba-2fa1-11d2-883f-0016d3cca427',
      training_session_id: 11,
      rpe_rating: 9,
    });
    expect(input.exercises[0].sets).toEqual([
      { set_number: 1, reps: 10, weight: 60, completed: true, rpe: null },
      { set_number: 2, reps: 8, weight: 60, completed: true, rpe: null },
    ]);
    expect(await screen.findByText('Workout saved')).toBeOnTheScreen();
    expect(screen.getByText('Barbell back squat: 60 → 55 kg')).toBeOnTheScreen();
    expect(screen.getByText('The workout felt very hard (RPE 9 or more), so the next one is lighter')).toBeOnTheScreen();
    expect(screen.getByText('Barbell back squat: 60 kg × 10')).toBeOnTheScreen();
  });

  it('asks for the overall RPE and warns about sets that are not ticked', async () => {
    await renderWithTheme(<WorkoutScreen />);
    await screen.findByText('Full Body A');

    expect(screen.getByText('2 sets are not ticked and will be saved as not completed.')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Save workout' }));

    expect(screen.getByText('Rate the whole workout (RPE) before saving.')).toBeOnTheScreen();
    expect(mockLogWorkout).not.toHaveBeenCalled();
  });

  it('keeps the same client_uuid when a failed save is repeated', async () => {
    mockLogWorkout.mockRejectedValueOnce(new TypeError('Network request failed'));
    mockLogWorkout.mockResolvedValueOnce({ workout: { id: 7 }, adjustments: [], new_personal_records: [] });
    await renderWithTheme(<WorkoutScreen />);
    await screen.findByText('Full Body A');
    await fireEvent.press(screen.getByRole('radio', { name: '6' }));

    await fireEvent.press(screen.getByRole('button', { name: 'Save workout' }));
    expect(screen.getByText('Cannot reach the server. Check your internet connection and try again.')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Save workout' }));

    expect(mockLogWorkout.mock.calls[1][0].client_uuid).toBe(mockLogWorkout.mock.calls[0][0].client_uuid);
    expect(await screen.findByText('Your plan stays the same for the next workout.')).toBeOnTheScreen();
  });
});

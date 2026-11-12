import { fireEvent, screen } from '@testing-library/react-native';
import { useEffect } from 'react';

import { ApiError } from '@/api/errors';
import TrainingScreen from '@/app/(tabs)/training';
import { renderWithTheme } from '@/test-utils';
import type { SessionExercise, TrainingPlan } from '@/training/training-api';

const mockUseEffect = useEffect;
const mockPush = jest.fn();
jest.mock('expo-router', () => ({
  router: { push: (...args: unknown[]) => mockPush(...args) },
  // Runs once on mount, as when the tab is first opened
  useFocusEffect: (effect: () => void) => mockUseEffect(effect, []),
}));
jest.mock('@/auth/session', () => ({
  useSession: () => ({ profile: { goal: 'muscle_gain', experience_level: 'beginner', equipment: 'gym' } }),
}));

const mockGetActivePlan = jest.fn();
const mockGetDraftPlan = jest.fn();
const mockGeneratePlan = jest.fn();
const mockAcceptPlan = jest.fn();
const mockScheduleSessions = jest.fn();
const mockGetNextSession = jest.fn();
const mockEditSessionExercise = jest.fn();
const mockGetAlternatives = jest.fn();
const mockSwapSessionExercise = jest.fn();
jest.mock('@/training/training-api', () => ({
  ...jest.requireActual('@/training/training-api'),
  getActivePlan: () => mockGetActivePlan(),
  getDraftPlan: () => mockGetDraftPlan(),
  generatePlan: (...args: unknown[]) => mockGeneratePlan(...args),
  acceptPlan: (...args: unknown[]) => mockAcceptPlan(...args),
  scheduleSessions: (...args: unknown[]) => mockScheduleSessions(...args),
  getNextSession: () => mockGetNextSession(),
  editSessionExercise: (...args: unknown[]) => mockEditSessionExercise(...args),
  getAlternatives: (...args: unknown[]) => mockGetAlternatives(...args),
  swapSessionExercise: (...args: unknown[]) => mockSwapSessionExercise(...args),
}));

function plan(status: TrainingPlan['status'], extra: Partial<TrainingPlan> = {}): TrainingPlan {
  return {
    id: status === 'draft' ? 2 : 1,
    plan_name: 'Muscle gain, 2 days per week',
    goal: 'muscle_gain',
    num_training_days: 2,
    experience_level: 'beginner',
    equipment: 'gym',
    generated_at: '2026-11-10T10:00:00Z',
    start_date: status === 'draft' ? null : '2026-11-02',
    end_date: status === 'draft' ? null : '2026-12-28',
    status,
    skipped_muscle_groups: [],
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
            planned_sets: 3,
            planned_reps: 10,
            planned_weight: 60,
            rest_seconds: 120,
          },
        ] as SessionExercise[],
      },
      {
        id: 12,
        session_order: 2,
        session_name: 'Full Body B',
        day_of_week: 4,
        estimated_duration: 45,
        exercises: [
          {
            id: 102,
            exercise_id: 6,
            exercise_name: 'Push-up',
            sort_order: 1,
            planned_sets: 3,
            planned_reps: 12,
            planned_weight: null,
            rest_seconds: 60,
          },
        ] as SessionExercise[],
      },
    ],
    ...extra,
  };
}

const press = (name: string) => fireEvent.press(screen.getByRole('button', { name }));
const toggleDay = (name: string) => fireEvent.press(screen.getByRole('checkbox', { name }));

describe('TrainingScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetActivePlan.mockResolvedValue(null);
    mockGetDraftPlan.mockResolvedValue(null);
    mockScheduleSessions.mockImplementation((p: TrainingPlan) => Promise.resolve(p));
    mockGetNextSession.mockResolvedValue(null);
  });

  it('generates a draft from the profile settings on the chosen weekdays', async () => {
    const draft = plan('draft');
    mockGeneratePlan.mockResolvedValue(draft);
    await renderWithTheme(<TrainingScreen />);

    expect(await screen.findByText('Create your training plan')).toBeOnTheScreen();
    expect(screen.getByText('Muscle gain · Beginner · Gym equipment')).toBeOnTheScreen();
    // The split's days (Mon, Wed, Fri) are chosen at the start
    expect(screen.getByText('3 days a week · Mon: Full Body A · Wed: Full Body B · Fri: Full Body C')).toBeOnTheScreen();
    for (const day of ['Mon', 'Wed', 'Fri', 'Tue', 'Thu', 'Sun']) {
      await toggleDay(day);
    }
    expect(screen.getByText('3 days a week · Tue: Full Body A · Thu: Full Body B · Sun: Full Body C')).toBeOnTheScreen();
    await press('Generate plan');

    expect(mockGeneratePlan).toHaveBeenCalledWith({
      goal: 'muscle_gain',
      num_training_days: 3,
      experience_level: 'beginner',
      equipment: 'gym',
    });
    expect(mockScheduleSessions).toHaveBeenCalledWith(draft, [2, 4, 7]);
    expect(await screen.findByText('Draft · not started yet')).toBeOnTheScreen();
    expect(screen.getByText('1. Barbell back squat')).toBeOnTheScreen();
  });

  it('asks for at least one day', async () => {
    await renderWithTheme(<TrainingScreen />);
    await screen.findByText('Create your training plan');
    for (const day of ['Mon', 'Wed', 'Fri']) {
      await toggleDay(day);
    }
    await press('Generate plan');

    expect(screen.getByText('Choose at least one day.')).toBeOnTheScreen();
    expect(mockGeneratePlan).not.toHaveBeenCalled();
  });

  it('keeps the draft when its days cannot be changed', async () => {
    mockGeneratePlan.mockResolvedValue(plan('draft'));
    mockScheduleSessions.mockRejectedValue(new ApiError(409, 'conflict', 'Taken', []));
    await renderWithTheme(<TrainingScreen />);
    await screen.findByText('Create your training plan');
    await press('Generate plan');

    expect(await screen.findByText('Draft · not started yet')).toBeOnTheScreen();
    expect(screen.getByText(/Your plan is ready, but its days could not be changed/)).toBeOnTheScreen();
  });

  it('shows the 422 suggestions and generates again with one (M-10 Done)', async () => {
    mockGeneratePlan
      .mockRejectedValueOnce(
        new ApiError(422, 'insufficient_exercises', 'Not enough exercises', [
          { field: 'muscle_group', code: 'no_eligible_exercise', message: 'x', muscle_group: 'back' },
          { code: 'change_equipment', message: 'x', equipment: 'home' },
          { code: 'change_goal', message: 'x', goals: ['strength'] },
        ]),
      )
      .mockResolvedValueOnce(plan('draft'));
    await renderWithTheme(<TrainingScreen />);
    await screen.findByText('Create your training plan');

    await press('Generate plan');

    expect(screen.getByText('No exercise fits your level and equipment for: back.')).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Goal: Strength' })).toBeOnTheScreen();
    await press('Use home equipment');

    expect(mockGeneratePlan).toHaveBeenLastCalledWith({
      goal: 'muscle_gain',
      num_training_days: 3,
      experience_level: 'beginner',
      equipment: 'home',
    });
    expect(await screen.findByText('Draft · not started yet')).toBeOnTheScreen();
  });

  it('explains a 422 without suggestions when injuries skip every group', async () => {
    mockGeneratePlan.mockRejectedValue(new ApiError(422, 'insufficient_exercises', 'Not enough exercises', []));
    await renderWithTheme(<TrainingScreen />);
    await screen.findByText('Create your training plan');
    await press('Generate plan');

    expect(screen.getByText(/Your injuries leave out every muscle group/)).toBeOnTheScreen();
  });

  it('shows the active plan one training day at a time', async () => {
    mockGetActivePlan.mockResolvedValue(plan('active'));
    await renderWithTheme(<TrainingScreen />);

    expect(await screen.findByText('Active · 2 Nov 2026 – 28 Dec 2026')).toBeOnTheScreen();
    expect(screen.getByText('3 sets × 10 reps · 60 kg · rest 120 s')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('radio', { name: 'Thu, Full Body B' }));
    expect(screen.getByText('1. Push-up')).toBeOnTheScreen();
    expect(screen.getByText('3 sets × 12 reps · rest 60 s')).toBeOnTheScreen();
  });

  it('moves the active plan to other weekdays', async () => {
    const active = plan('active');
    mockGetActivePlan.mockResolvedValue(active);
    await renderWithTheme(<TrainingScreen />);
    await screen.findByText('Active · 2 Nov 2026 – 28 Dec 2026');
    expect(screen.getByText('Muscle gain · Beginner · Gym equipment')).toBeOnTheScreen();

    await press('Change training days');
    await toggleDay('Tue');
    await press('Save days');
    expect(screen.getByText('Choose 2 days.')).toBeOnTheScreen();

    await toggleDay('Mon');
    await press('Save days');
    expect(mockScheduleSessions).toHaveBeenCalledWith(active, [2, 4]);
    expect(await screen.findByText('Training days saved.')).toBeOnTheScreen();
  });

  it('accepts a draft, which then replaces the current plan', async () => {
    mockGetActivePlan.mockResolvedValue(plan('active', { plan_name: 'Old plan' }));
    mockGetDraftPlan.mockResolvedValue(plan('draft'));
    mockAcceptPlan.mockResolvedValue(plan('active', { id: 2, start_date: '2026-11-10', end_date: '2027-01-05' }));
    await renderWithTheme(<TrainingScreen />);

    expect(await screen.findByText('Accepting it replaces your current plan.')).toBeOnTheScreen();
    await press('Accept plan');

    expect(mockAcceptPlan).toHaveBeenCalledWith(2);
    expect(await screen.findByText('Your plan has started. It runs until 5 Jan 2027.')).toBeOnTheScreen();
    expect(screen.queryByRole('radio', { name: 'New draft' })).not.toBeOnTheScreen();
  });

  it('starts the next workout of the active plan', async () => {
    const active = plan('active');
    mockGetActivePlan.mockResolvedValue(active);
    mockGetNextSession.mockResolvedValue({ training_plan_id: 1, date: '2026-11-12', session: active.sessions[1] });
    await renderWithTheme(<TrainingScreen />);

    expect(await screen.findByText('Thu, 12 Nov')).toBeOnTheScreen();
    await press('Start workout');
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/workout', params: { sessionId: '12' } });

    await press('Start this workout');
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: '/workout', params: { sessionId: '11' } });
  });

  describe('changing a planned exercise (FR-A1)', () => {
    const squat = plan('active').sessions[0].exercises[0];
    const openSquat = async () => {
      mockGetActivePlan.mockResolvedValue(plan('active'));
      await renderWithTheme(<TrainingScreen />);
      await screen.findByText('Tap an exercise to change it.');
      await fireEvent.press(screen.getByRole('button', { name: /^Barbell back squat/ }));
    };

    it('sends only the changed fields and shows them at once', async () => {
      mockEditSessionExercise.mockResolvedValue({ ...squat, planned_sets: 4, planned_weight: 62.5 });
      await openSquat();

      await fireEvent.changeText(screen.getByLabelText('Sets'), '0');
      await press('Save changes');
      expect(screen.getByText('Enter a number from 1 to 32767.')).toBeOnTheScreen();
      expect(mockEditSessionExercise).not.toHaveBeenCalled();

      await fireEvent.changeText(screen.getByLabelText('Sets'), '4');
      await fireEvent.changeText(screen.getByLabelText('Weight'), '62,5');
      await press('Save changes');

      expect(mockEditSessionExercise).toHaveBeenCalledWith(101, { planned_sets: 4, planned_weight: 62.5 });
      expect(await screen.findByText('Barbell back squat updated.')).toBeOnTheScreen();
      expect(screen.getByText('4 sets × 10 reps · 62.5 kg · rest 120 s')).toBeOnTheScreen();
    });

    it('swaps the exercise for an alternative', async () => {
      mockGetAlternatives.mockResolvedValue([
        {
          id: 9,
          name: 'Goblet squat',
          difficulty_level: 'beginner',
          equipment: 'home',
          is_compound: true,
          is_bodyweight: false,
          description: '',
          instruction: '',
          muscle_groups: [],
        },
      ]);
      mockSwapSessionExercise.mockResolvedValue({ ...squat, exercise_id: 9, exercise_name: 'Goblet squat' });
      await openSquat();

      await press('Swap exercise');
      expect(mockGetAlternatives).toHaveBeenCalledWith(squat);
      await fireEvent.press(await screen.findByRole('button', { name: /^Goblet squat/ }));

      expect(mockSwapSessionExercise).toHaveBeenCalledWith(101, 9);
      expect(await screen.findByText('Barbell back squat swapped for Goblet squat.')).toBeOnTheScreen();
      expect(screen.getByText('1. Goblet squat')).toBeOnTheScreen();
    });

    it('points to the injuries when the exercise hurts', async () => {
      await openSquat();

      await fireEvent.press(screen.getByRole('radio', { name: 'It hurts' }));
      expect(screen.getByText(/Add the injury to your profile/)).toBeOnTheScreen();
      await press('Add an injury');
      expect(mockPush).toHaveBeenCalledWith('/edit-profile');
    });

    it('explains that an archived plan cannot be changed', async () => {
      mockEditSessionExercise.mockRejectedValue(new ApiError(409, 'conflict', 'Plan is archived', []));
      await openSquat();

      await fireEvent.changeText(screen.getByLabelText('Reps'), '8');
      await press('Save changes');
      expect(await screen.findByText('This plan can no longer be changed. Open your current plan.')).toBeOnTheScreen();
    });
  });
});

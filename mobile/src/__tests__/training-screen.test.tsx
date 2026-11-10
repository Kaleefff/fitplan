import { fireEvent, screen } from '@testing-library/react-native';
import { useEffect } from 'react';

import { ApiError } from '@/api/errors';
import TrainingScreen from '@/app/(tabs)/training';
import { renderWithTheme } from '@/test-utils';
import type { TrainingPlan } from '@/training/training-api';

const mockUseEffect = useEffect;
jest.mock('expo-router', () => ({
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
jest.mock('@/training/training-api', () => ({
  ...jest.requireActual('@/training/training-api'),
  getActivePlan: () => mockGetActivePlan(),
  getDraftPlan: () => mockGetDraftPlan(),
  generatePlan: (...args: unknown[]) => mockGeneratePlan(...args),
  acceptPlan: (...args: unknown[]) => mockAcceptPlan(...args),
  scheduleSessions: (...args: unknown[]) => mockScheduleSessions(...args),
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
        ],
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
        ],
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
});

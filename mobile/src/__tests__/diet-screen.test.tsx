import { fireEvent, screen } from '@testing-library/react-native';
import { useEffect } from 'react';

import { ApiError } from '@/api/errors';
import DietScreen from '@/app/(tabs)/diet';
import type { DietPlan } from '@/diet/diet-api';
import { renderWithTheme } from '@/test-utils';
import { isoDate } from '@/utils/dates';

const mockUseEffect = useEffect;
jest.mock('expo-router', () => ({
  useFocusEffect: (effect: () => void) => mockUseEffect(effect, []),
}));
jest.mock('@/auth/session', () => ({ useSession: () => ({ profile: { profile_update: '2026-11-10T10:00:00Z' } }) }));
jest.mock('@/hooks/use-nutrition-targets', () => ({
  useNutritionTargets: () => ({ state: { status: 'ready', targets: { tdee: 2798 } }, retry: jest.fn() }),
}));

const mockGetActive = jest.fn();
const mockGetDraft = jest.fn();
const mockGenerate = jest.fn();
const mockAccept = jest.fn();
jest.mock('@/diet/diet-api', () => ({
  ...jest.requireActual('@/diet/diet-api'),
  getActiveDietPlan: () => mockGetActive(),
  getDraftDietPlan: () => mockGetDraft(),
  generateDietPlan: (...args: unknown[]) => mockGenerate(...args),
  acceptDietPlan: (...args: unknown[]) => mockAccept(...args),
}));

function meal(day: number, order: number, extra: Partial<DietPlan['meals'][number]> = {}): DietPlan['meals'][number] {
  return {
    id: day * 10 + order,
    day_index: day,
    meal_type: order === 1 ? 'breakfast' : order === 2 ? 'lunch' : 'dinner',
    meal_order: order,
    planned_time: order === 1 ? '08:00:00' : order === 2 ? '13:00:00' : '19:00:00',
    planned_cals: 900 + order,
    planned_protein: 40.5,
    planned_fat: 30,
    planned_carbs: 120.25,
    items: [{ food_item_id: day * 100 + order, name: `Food ${day}.${order}`, grams: 150 }],
    ...extra,
  };
}

function plan(status: DietPlan['status'], extra: Partial<DietPlan> = {}): DietPlan {
  return {
    id: status === 'draft' ? 2 : 1,
    name: 'Muscle gain diet, 3 meals',
    goal: 'muscle_gain',
    diet_type: 'omnivore',
    meals_per_day: 3,
    generated_at: '2026-11-10T10:00:00Z',
    start_date: null,
    end_date: null,
    daily_cal_goal: 3078,
    protein_goal: 144,
    fat_goal: 85.5,
    carbs_goal: 433.1,
    status,
    dietary_restrictions: null,
    meals: [1, 2, 3, 4, 5, 6, 7].flatMap((day) => [meal(day, 1), meal(day, 2), meal(day, 3)]),
    ...extra,
  };
}

const press = (name: string) => fireEvent.press(screen.getByRole('button', { name }));

describe('DietScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetActive.mockResolvedValue(null);
    mockGetDraft.mockResolvedValue(null);
  });

  it('generates a draft and shows the targets of the API answer (M-11 Done)', async () => {
    mockGenerate.mockResolvedValue(plan('draft'));
    await renderWithTheme(<DietScreen />);

    expect(await screen.findByText('Create your diet plan')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('radio', { name: '3' }));
    await fireEvent.press(screen.getByRole('radio', { name: 'Vegetarian' }));
    await fireEvent.changeText(screen.getByLabelText('Notes (optional)'), '  no spicy food ');
    await press('Generate diet plan');

    expect(mockGenerate).toHaveBeenCalledWith({
      meals_per_day: 3,
      diet_type: 'vegetarian',
      dietary_restrictions: 'no spicy food',
    });
    expect(await screen.findByText('3078')).toBeOnTheScreen();
    expect(screen.getByText('Your energy need (TDEE) is 2798 kcal')).toBeOnTheScreen();
    expect(screen.getByLabelText('Fats 85.5 grams')).toBeOnTheScreen();
    expect(screen.getByLabelText('Carbs 433.1 grams')).toBeOnTheScreen();
    expect(screen.getByText('Breakfast · 08:00')).toBeOnTheScreen();
    expect(screen.getAllByText('Protein 40.5 g · Fat 30 g · Carbs 120.3 g')).toHaveLength(3);
    expect(screen.getByText('Food 1.1')).toBeOnTheScreen();
    expect(screen.getByText('Planned for day 1: 2706 kcal')).toBeOnTheScreen();

    await fireEvent.press(screen.getByRole('radio', { name: 'Day 4' }));
    expect(screen.getByText('Food 4.3')).toBeOnTheScreen();
  });

  it('explains a 422 insufficient_foods answer', async () => {
    mockGenerate.mockRejectedValue(
      new ApiError(422, 'insufficient_foods', 'Not enough foods', [
        { field: 'food', code: 'no_eligible_food', message: 'x', meal_type: 'breakfast', role: 'protein' },
      ]),
    );
    await renderWithTheme(<DietScreen />);
    await screen.findByText('Create your diet plan');
    await fireEvent.press(screen.getByRole('radio', { name: '4' }));
    await press('Generate diet plan');

    expect(
      screen.getByText(
        'No food fits your diet type, allergies and excluded foods for: Breakfast (protein). Try another diet type.',
      ),
    ).toBeOnTheScreen();
  });

  it('opens the active plan on today and accepts a new draft', async () => {
    mockGetActive.mockResolvedValue(plan('active', { start_date: isoDate(), end_date: '2027-01-05' }));
    mockGetDraft.mockResolvedValue(plan('draft', { name: 'Maintenance diet, 3 meals' }));
    mockAccept.mockResolvedValue(plan('active', { id: 2, start_date: '2026-11-10', end_date: '2027-01-05' }));
    await renderWithTheme(<DietScreen />);

    await fireEvent.press(await screen.findByRole('radio', { name: 'Current plan' }));
    expect(screen.getByRole('radio', { name: 'Day 1, Today' })).toBeSelected();

    await fireEvent.press(screen.getByRole('radio', { name: 'New draft' }));
    await press('Accept plan');
    expect(mockAccept).toHaveBeenCalledWith(2);
    expect(await screen.findByText('Your diet plan has started. It runs until 5 Jan 2027.')).toBeOnTheScreen();
  });
});

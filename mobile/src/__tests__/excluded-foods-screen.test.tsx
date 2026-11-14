import { fireEvent, screen } from '@testing-library/react-native';

import { ApiError } from '@/api/errors';
import ExcludedFoodsScreen from '@/app/excluded-foods';
import type { DietPlan, FoodItem } from '@/diet/diet-api';
import { renderWithTheme } from '@/test-utils';

let mockParams: { add?: string } = {};
const mockNavigate = jest.fn();
jest.mock('expo-router', () => ({
  router: { navigate: (...args: unknown[]) => mockNavigate(...args), back: jest.fn() },
  useLocalSearchParams: () => mockParams,
}));

const mockGetExcluded = jest.fn();
const mockSaveExcluded = jest.fn();
const mockSearch = jest.fn();
const mockGetFood = jest.fn();
const mockGetActive = jest.fn();
const mockGetDraft = jest.fn();
const mockGenerate = jest.fn();
jest.mock('@/diet/diet-api', () => ({
  ...jest.requireActual('@/diet/diet-api'),
  getExcludedFoods: () => mockGetExcluded(),
  saveExcludedFoods: (...args: unknown[]) => mockSaveExcluded(...args),
  searchFoods: (...args: unknown[]) => mockSearch(...args),
  getFood: (...args: unknown[]) => mockGetFood(...args),
  getActiveDietPlan: () => mockGetActive(),
  getDraftDietPlan: () => mockGetDraft(),
  generateDietPlan: (...args: unknown[]) => mockGenerate(...args),
}));

const food = (id: number, name: string) => ({ id, name, cals_per_100g: 34 }) as FoodItem;
const broccoli = food(3, 'Broccoli');
const oats = food(1, 'Oats');

const activePlan = {
  id: 1,
  status: 'active',
  meals_per_day: 3,
  diet_type: 'omnivore',
  dietary_restrictions: 'No spicy food',
  meals: [{ items: [{ food_item_id: 3, name: 'Broccoli', grams: 150 }] }],
} as unknown as DietPlan;

const toggle = (name: string) => fireEvent.press(screen.getByRole('checkbox', { name: `Exclude ${name}` }));
const save = () => fireEvent.press(screen.getByRole('button', { name: 'Save' }));
const SAVED = 'Excluded foods saved. New diet plans leave them out.';

describe('ExcludedFoodsScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockParams = {};
    mockGetExcluded.mockResolvedValue([oats]);
    mockSaveExcluded.mockImplementation((ids: number[]) =>
      Promise.resolve([oats, broccoli].filter((f) => ids.includes(f.id))),
    );
    mockGetActive.mockResolvedValue(null);
    mockGetDraft.mockResolvedValue(null);
  });

  it('finds a food and saves the whole list', async () => {
    mockSearch.mockResolvedValue([broccoli]);
    await renderWithTheme(<ExcludedFoodsScreen />);
    expect(await screen.findByText('Oats')).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();

    await fireEvent.changeText(screen.getByLabelText('Find a food'), 'b');
    await fireEvent.changeText(screen.getByLabelText('Find a food'), 'broc');
    expect(await screen.findByRole('checkbox', { name: 'Exclude Broccoli' })).toBeOnTheScreen();
    expect(mockSearch).toHaveBeenCalledTimes(1);
    expect(mockSearch).toHaveBeenCalledWith('broc');

    await toggle('Broccoli');
    await save();

    expect(mockSaveExcluded).toHaveBeenCalledWith([1, 3]);
    expect(await screen.findByText(SAVED)).toBeOnTheScreen();
  });

  it('adds the food tapped in the plan and offers a new plan without it', async () => {
    mockParams = { add: '3' };
    mockGetFood.mockResolvedValue(broccoli);
    mockGetActive.mockResolvedValue(activePlan);
    mockGenerate.mockResolvedValue({ ...activePlan, id: 2, status: 'draft' });
    await renderWithTheme(<ExcludedFoodsScreen />);

    expect(await screen.findByRole('checkbox', { name: 'Exclude Broccoli' })).toBeOnTheScreen();
    expect(mockGetFood).toHaveBeenCalledWith(3);
    await save();

    expect(await screen.findByText('Your current diet plan has foods you excluded')).toBeOnTheScreen();
    expect(screen.getByText('Broccoli. Generate a new plan without them?')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Generate new plan' }));

    expect(mockGenerate).toHaveBeenCalledWith({
      meals_per_day: 3,
      diet_type: 'omnivore',
      dietary_restrictions: 'No spicy food',
    });
    expect(await screen.findByText('A new draft is ready')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Open the Diet tab' }));
    expect(mockNavigate).toHaveBeenCalledWith('/diet');
  });

  it('removes a food and offers nothing for a plan without excluded foods', async () => {
    mockGetActive.mockResolvedValue(activePlan);
    await renderWithTheme(<ExcludedFoodsScreen />);
    await screen.findByText('Oats');

    await toggle('Oats');
    expect(screen.getByText('No foods excluded.')).toBeOnTheScreen();
    await save();

    expect(mockSaveExcluded).toHaveBeenCalledWith([]);
    await screen.findByText(SAVED);
    expect(screen.queryByText('Generate new plan')).not.toBeOnTheScreen();
  });

  it('explains when the new plan cannot be made', async () => {
    mockParams = { add: '3' };
    mockGetFood.mockResolvedValue(broccoli);
    mockGetActive.mockResolvedValue(activePlan);
    mockGenerate.mockRejectedValue(new ApiError(422, 'insufficient_foods', 'Not enough foods', []));
    await renderWithTheme(<ExcludedFoodsScreen />);
    await screen.findByRole('checkbox', { name: 'Exclude Broccoli' });

    await save();
    await fireEvent.press(await screen.findByRole('button', { name: 'Generate new plan' }));

    expect(
      await screen.findByText(
        'The plan could not reach your daily targets with the foods that fit you. Try another diet type or number of meals.',
      ),
    ).toBeOnTheScreen();
  });

  it('keeps the list when the server rejects it', async () => {
    mockSaveExcluded.mockRejectedValue(new ApiError(422, 'validation_error', 'Invalid input', []));
    await renderWithTheme(<ExcludedFoodsScreen />);
    await screen.findByText('Oats');

    await toggle('Oats');
    await save();

    expect(
      await screen.findByText('One of these foods is no longer in the food database. Remove it and save again.'),
    ).toBeOnTheScreen();
  });
});

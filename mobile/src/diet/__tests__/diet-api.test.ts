import { ApiError } from '@/api/errors';
import {
  dayIndexOn,
  dietSettingsOf,
  excludedInPlan,
  getFood,
  saveExcludedFoods,
  searchFoods,
  type DietPlan,
} from '@/diet/diet-api';
import { grams } from '@/diet/labels';

const mockGet = jest.fn();
const mockPut = jest.fn();
jest.mock('@/api/client', () => ({
  api: {
    GET: (...args: unknown[]) => mockGet(...args),
    PUT: (...args: unknown[]) => mockPut(...args),
  },
  unwrap: (call: Promise<unknown>) => call,
}));

describe('diet plan helpers', () => {
  // algorithms.md 5.1: today's day = ((date − start_date) mod 7) + 1
  it('finds the day of the 7-day plan', () => {
    expect(dayIndexOn('2026-11-10', '2026-11-10')).toBe(1);
    expect(dayIndexOn('2026-11-10', '2026-11-16')).toBe(7);
    expect(dayIndexOn('2026-11-10', '2026-11-17')).toBe(1);
    expect(dayIndexOn('2026-11-10', '2026-12-01')).toBe(1);
    // A plan that starts tomorrow
    expect(dayIndexOn('2026-11-11', '2026-11-10')).toBe(7);
  });

  it('prints grams as the API gives them', () => {
    expect(grams(144)).toBe('144');
    expect(grams(85.5)).toBe('85.5');
    expect(grams(433.12)).toBe('433.1');
  });
});

describe('excluded foods (FR-P6, algorithms.md 5.2)', () => {
  beforeEach(() => jest.clearAllMocks());

  const plan = {
    meals_per_day: 3,
    diet_type: 'vegetarian',
    dietary_restrictions: null,
    meals: [
      {
        items: [
          { food_item_id: 1, name: 'Oats', grams: 80 },
          { food_item_id: 2, name: 'Milk', grams: 200 },
        ],
      },
      {
        items: [
          { food_item_id: 3, name: 'Broccoli', grams: 150 },
          { food_item_id: 1, name: 'Oats', grams: 60 },
        ],
      },
    ],
  } as unknown as DietPlan;

  it('names the plan foods that are excluded, each once', () => {
    expect(excludedInPlan(plan, [1, 3, 99])).toEqual(['Oats', 'Broccoli']);
    expect(excludedInPlan(plan, [99])).toEqual([]);
  });

  it('generates again with the settings of the plan', () => {
    expect(dietSettingsOf(plan)).toEqual({ meals_per_day: 3, diet_type: 'vegetarian', dietary_restrictions: null });
  });

  it('calls the contract endpoints', async () => {
    mockGet.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    mockPut.mockResolvedValue([]);

    await searchFoods('brocc');
    await saveExcludedFoods([3, 1]);

    expect(mockGet).toHaveBeenCalledWith('/foods', { params: { query: { q: 'brocc', limit: 20 } } });
    expect(mockPut).toHaveBeenCalledWith('/users/me/excluded-foods', { body: { food_item_ids: [3, 1] } });
  });

  it('gives null for an unknown or inactive food', async () => {
    mockGet.mockRejectedValue(new ApiError(404, 'not_found', 'Not found', []));
    expect(await getFood(5)).toBeNull();
  });
});

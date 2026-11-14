import { api, unwrap } from '@/api/client';
import { ApiError } from '@/api/errors';
import type { components } from '@/api/schema';
import { createDraftStore } from '@/plans/draft-store';
import { daysBetween } from '@/utils/dates';

type Schemas = components['schemas'];
export type DietPlan = Schemas['DietPlan'];
export type Meal = Schemas['Meal'];
export type GenerateDietPlanRequest = Schemas['GenerateDietPlanRequest'];
export type DietType = NonNullable<GenerateDietPlanRequest['diet_type']>;
export type FoodItem = Schemas['FoodItem'];

export const dietDraft = createDraftStore('fitplan.dietDraftId');

export async function getActiveDietPlan(): Promise<DietPlan | null> {
  try {
    return await unwrap(api.GET('/diet-plans/active'));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** The remembered draft, or null when it was accepted, replaced or is not found */
export async function getDraftDietPlan(): Promise<DietPlan | null> {
  const id = await dietDraft.get();
  if (id === null) {
    return null;
  }
  let plan: DietPlan | null = null;
  try {
    plan = await unwrap(api.GET('/diet-plans/{plan_id}', { params: { path: { plan_id: id } } }));
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) {
      throw error;
    }
  }
  if (plan?.status !== 'draft') {
    await dietDraft.clear();
    return null;
  }
  return plan;
}

/** Throws ApiError 422 `insufficient_foods` when the targets cannot be met (algorithms.md 5.5) */
export async function generateDietPlan(input: GenerateDietPlanRequest): Promise<DietPlan> {
  const plan = await unwrap(api.POST('/diet-plans/generate', { body: input }));
  await dietDraft.set(plan.id);
  return plan;
}

/** Starts today; the previous active plan is archived (FR-P7) */
export async function acceptDietPlan(planId: number): Promise<DietPlan> {
  const plan = await unwrap(api.POST('/diet-plans/{plan_id}/accept', { params: { path: { plan_id: planId } } }));
  await dietDraft.clear();
  return plan;
}

/** Day of the 7-day plan that falls on `today`: ((date − start_date) mod 7) + 1, algorithms.md 5.1 */
export function dayIndexOn(startDate: string, today: string): number {
  return (((daysBetween(startDate, today) % 7) + 7) % 7) + 1;
}

/** The settings of a plan, to generate it again with the same choices (FR-P7) */
export function dietSettingsOf(plan: DietPlan): GenerateDietPlanRequest {
  return {
    meals_per_day: plan.meals_per_day,
    diet_type: plan.diet_type,
    dietary_restrictions: plan.dietary_restrictions ?? null,
  };
}

/** Foods the user never wants in a diet plan (algorithms.md 5.2) */
export function getExcludedFoods(): Promise<FoodItem[]> {
  return unwrap(api.GET('/users/me/excluded-foods'));
}

/** Replaces the whole list; an unknown or inactive id is 422 and nothing changes (api-rules.md Profile) */
export function saveExcludedFoods(foodIds: number[]): Promise<FoodItem[]> {
  return unwrap(api.PUT('/users/me/excluded-foods', { body: { food_item_ids: foodIds } }));
}

export const FOOD_SEARCH_LIMIT = 20;

/** First page of the food database matching the text (FR-P8) */
export async function searchFoods(text: string): Promise<FoodItem[]> {
  const page = await unwrap(api.GET('/foods', { params: { query: { q: text, limit: FOOD_SEARCH_LIMIT } } }));
  return page.items;
}

/** null when the food is unknown or no longer active */
export async function getFood(foodId: number): Promise<FoodItem | null> {
  try {
    return await unwrap(api.GET('/foods/{food_id}', { params: { path: { food_id: foodId } } }));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** Names of the plan's foods that are in the excluded list, each once, in plan order */
export function excludedInPlan(plan: DietPlan, excludedIds: number[]): string[] {
  const excluded = new Set(excludedIds);
  const names: string[] = [];
  for (const meal of plan.meals) {
    for (const item of meal.items) {
      if (excluded.has(item.food_item_id) && !names.includes(item.name)) {
        names.push(item.name);
      }
    }
  }
  return names;
}

import type { components } from '@/api/schema';

type MealType = components['schemas']['MealType'];

export const MEAL_TYPE_LABELS: Record<MealType, string> = {
  breakfast: 'Breakfast',
  lunch: 'Lunch',
  dinner: 'Dinner',
  snack: 'Snack',
};

/** Grams as the API gives them, without trailing zeros: 85.5 -> "85.5", 144 -> "144" */
export const grams = (value: number) => String(Number(value.toFixed(1)));

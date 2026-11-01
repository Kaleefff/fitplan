import type { components } from '@/api/schema';
import type { Option } from '@/components/option-group';

type Schemas = components['schemas'];
type ProfileInput = Schemas['ProfileInput'];

// Labels for the contract enums; values are exactly those of docs/api/openapi.yaml

export const SEX_OPTIONS: Option<Schemas['Sex']>[] = [
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'other', label: 'Other' },
];

// algorithms.md section 0: the PAL values the app offers
export const PAL_OPTIONS: Option<ProfileInput['activity_level_pal']>[] = [
  { value: 1.2, label: 'Sedentary', hint: 'PAL 1.2' },
  { value: 1.375, label: 'Light', hint: 'PAL 1.375' },
  { value: 1.55, label: 'Moderate', hint: 'PAL 1.55' },
  { value: 1.725, label: 'High', hint: 'PAL 1.725' },
  { value: 1.9, label: 'Very high', hint: 'PAL 1.9' },
];

export const GOAL_OPTIONS: Option<Schemas['Goal']>[] = [
  { value: 'weight_loss', label: 'Weight loss' },
  { value: 'muscle_gain', label: 'Muscle gain' },
  { value: 'strength', label: 'Strength' },
  { value: 'maintenance', label: 'Maintenance' },
  { value: 'general_fitness', label: 'General fitness' },
  { value: 'endurance', label: 'Endurance' },
];

export const LEVEL_OPTIONS: Option<Schemas['DifficultyLevel']>[] = [
  { value: 'beginner', label: 'Beginner' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'advanced', label: 'Advanced' },
];

// algorithms.md 4.2: equipment tiers and what belongs to them
export const EQUIPMENT_OPTIONS: Option<Schemas['Equipment']>[] = [
  { value: 'none', label: 'None', hint: 'Bodyweight, chair, wall, towel' },
  { value: 'home', label: 'Home', hint: 'Dumbbells, bands, bench, pull-up bar' },
  { value: 'gym', label: 'Gym', hint: 'Full gym' },
];

export const SEVERITY_OPTIONS: Option<Schemas['InjurySeverity']>[] = [
  { value: 'mild', label: 'Mild' },
  { value: 'moderate', label: 'Moderate' },
  { value: 'severe', label: 'Severe' },
];

/** "quadriceps" -> "Quadriceps" for names stored in lower case */
export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function labelOf<T>(options: Option<T>[], value: T | null | undefined): string {
  return options.find((option) => option.value === value)?.label ?? '–';
}

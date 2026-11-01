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

// The muscle group the plan generator spares (algorithms.md 4.3) for injury types that name one
// part of the body. Keys are type_name of database/seed/injury_type.csv, the seed's key. Types
// missing here, such as a fracture, can be anywhere or have no group of their own: the user is asked.
const INJURY_MUSCLE_GROUPS: Record<string, string> = {
  'Shoulder strain': 'shoulders',
  'Rotator cuff tendinopathy': 'shoulders',
  'Lower back strain': 'back',
  'Hamstring strain': 'hamstrings',
  'Knee pain': 'quadriceps',
  'Patellar tendinopathy': 'quadriceps',
  'Shin splints': 'calves',
  'Calf strain': 'calves',
  'Achilles tendinopathy': 'calves',
  'Ankle sprain': 'calves',
};

export function muscleGroupOfInjury(typeName: string): string | null {
  return INJURY_MUSCLE_GROUPS[typeName] ?? null;
}

// How long the user has had an injury; the value is in months
export const INJURY_DURATION_OPTIONS: Option<number>[] = [
  { value: 0, label: 'Less than a month' },
  { value: 1, label: '1–12 months' },
  { value: 12, label: '1–3 years' },
  { value: 36, label: 'More than 3 years' },
];

/** YYYY-MM-DD the given number of months before now, in the phone's time zone */
export function monthsAgo(months: number, now: Date = new Date()): string {
  const date = new Date(now.getFullYear(), now.getMonth() - months, now.getDate());
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * The API stores an exact start_date, the user gives a range: the date sent is monthsAgo(value),
 * the newest day of the range. This reads the range back from that date.
 */
export function injuryDurationLabel(startDate: string, now: Date = new Date()): string {
  const longestFirst = [...INJURY_DURATION_OPTIONS].reverse();
  return longestFirst.find((option) => startDate <= monthsAgo(option.value, now))?.label ?? '–';
}

/** "quadriceps" -> "Quadriceps" for names stored in lower case */
export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function labelOf<T>(options: Option<T>[], value: T | null | undefined): string {
  return options.find((option) => option.value === value)?.label ?? '–';
}

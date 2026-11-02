import type { components } from '@/api/schema';

type ProfileInput = components['schemas']['ProfileInput'];

// Ranges of FR-U7 and algorithms.md section 0, the same as ProfileInput in the contract
export const AGE_RANGE = { min: 16, max: 100 };
export const WEIGHT_RANGE = { min: 30, max: 300 };
export const HEIGHT_RANGE = { min: 120, max: 250 };

/** What the wizard holds while the user types: numbers stay text until they are checked */
export type ProfileForm = {
  age: string;
  sex: ProfileInput['sex'] | null;
  current_weight: string;
  height: string;
  activity_level_pal: ProfileInput['activity_level_pal'] | null;
  goal: ProfileInput['goal'] | null;
  target_value: string;
  experience_level: ProfileInput['experience_level'] | null;
  equipment: ProfileInput['equipment'] | null;
};

export const EMPTY_PROFILE_FORM: ProfileForm = {
  age: '',
  sex: null,
  current_weight: '',
  height: '',
  activity_level_pal: null,
  goal: null,
  target_value: '',
  experience_level: null,
  equipment: null,
};

const REQUIRED = 'This field is required.';
const CHOOSE = 'Choose an option.';

/** "80,5" and "80.5" both work; returns null for empty or non-numeric text */
export function parseNumber(text: string): number | null {
  const normalised = text.trim().replace(',', '.');
  if (!normalised || !/^\d+(\.\d+)?$/.test(normalised)) {
    return null;
  }
  return Number(normalised);
}

function checkNumber(
  text: string,
  range: { min: number; max: number },
  message: string,
  integer: boolean,
): string | undefined {
  if (!text.trim()) {
    return REQUIRED;
  }
  const value = parseNumber(text);
  if (value === null || (integer && !Number.isInteger(value)) || value < range.min || value > range.max) {
    return message;
  }
  return undefined;
}

type Check = (form: ProfileForm) => string | undefined;

const CHECKS: Record<keyof ProfileForm, Check> = {
  age: (f) => checkNumber(f.age, AGE_RANGE, 'Age must be a whole number between 16 and 100.', true),
  sex: (f) => (f.sex ? undefined : CHOOSE),
  current_weight: (f) => checkNumber(f.current_weight, WEIGHT_RANGE, 'Weight must be between 30 and 300 kg.', false),
  height: (f) => checkNumber(f.height, HEIGHT_RANGE, 'Height must be a whole number between 120 and 250 cm.', true),
  activity_level_pal: (f) => (f.activity_level_pal ? undefined : CHOOSE),
  goal: (f) => (f.goal ? undefined : CHOOSE),
  // Optional: only checked when filled in
  target_value: (f) =>
    f.target_value.trim()
      ? checkNumber(f.target_value, WEIGHT_RANGE, 'Target weight must be between 30 and 300 kg.', false)
      : undefined,
  experience_level: (f) => (f.experience_level ? undefined : CHOOSE),
  equipment: (f) => (f.equipment ? undefined : CHOOSE),
};

/** Errors of the given fields only, so each wizard step checks its own fields */
export function validateProfile(form: ProfileForm, fields: (keyof ProfileForm)[]): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const error = CHECKS[field](form);
    if (error) {
      errors[field] = error;
    }
  }
  return errors;
}

// user_profile stores weights as numeric(5,2)
const twoDecimals = (value: number) => Math.round(value * 100) / 100;

/** The request body; call only after validateProfile found no errors */
export function toProfileInput(form: ProfileForm): ProfileInput {
  const target = parseNumber(form.target_value);
  return {
    age: Number(parseNumber(form.age)),
    sex: form.sex!,
    current_weight: twoDecimals(Number(parseNumber(form.current_weight))),
    height: Number(parseNumber(form.height)),
    activity_level_pal: form.activity_level_pal!,
    goal: form.goal!,
    target_value: target === null ? null : twoDecimals(target),
    experience_level: form.experience_level!,
    equipment: form.equipment!,
  };
}

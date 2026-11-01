import { checkStartDate, localToday } from '@/profile/health-step';
import { EMPTY_PROFILE_FORM, parseNumber, toProfileInput, validateProfile, type ProfileForm } from '@/profile/validation';

const VALID: ProfileForm = {
  age: '25',
  sex: 'male',
  current_weight: '80',
  height: '180',
  activity_level_pal: 1.55,
  goal: 'muscle_gain',
  target_value: '',
  experience_level: 'beginner',
  equipment: 'gym',
};

const errorOf = (field: keyof ProfileForm, value: string) =>
  validateProfile({ ...VALID, [field]: value }, [field])[field];

describe('profile ranges (FR-U7)', () => {
  it.each([
    ['current_weight', '29', false],
    ['current_weight', '30', true],
    ['current_weight', '300', true],
    ['current_weight', '301', false],
    ['current_weight', '80,5', true],
    ['age', '15', false],
    ['age', '16', true],
    ['age', '100', true],
    ['age', '101', false],
    ['age', '25.5', false],
    ['height', '119', false],
    ['height', '120', true],
    ['height', '250', true],
    ['height', '251', false],
    ['target_value', '', true],
    ['target_value', '29', false],
  ] as const)('%s = "%s" -> valid: %s', (field, value, valid) => {
    expect(errorOf(field, value) === undefined).toBe(valid);
  });

  it('gives a clear message per missing field', () => {
    expect(validateProfile(EMPTY_PROFILE_FORM, ['age', 'sex', 'current_weight', 'goal'])).toEqual({
      age: 'This field is required.',
      sex: 'Choose an option.',
      current_weight: 'This field is required.',
      goal: 'Choose an option.',
    });
  });

  it('rejects text that is not a number', () => {
    expect(parseNumber('80kg')).toBeNull();
    expect(errorOf('current_weight', 'abc')).toBe('Weight must be between 30 and 300 kg.');
  });
});

describe('toProfileInput', () => {
  it('builds the contract body with numbers and null for an empty target', () => {
    expect(toProfileInput({ ...VALID, current_weight: '80,456', target_value: '' })).toEqual({
      age: 25,
      sex: 'male',
      current_weight: 80.46,
      height: 180,
      activity_level_pal: 1.55,
      goal: 'muscle_gain',
      target_value: null,
      experience_level: 'beginner',
      equipment: 'gym',
    });
  });
});

describe('injury start date', () => {
  it('accepts today and past dates, rejects future and invalid ones', () => {
    expect(checkStartDate(localToday())).toBeUndefined();
    expect(checkStartDate('2026-01-31')).toBeUndefined();
    expect(checkStartDate('2999-01-01')).toBe('The start date cannot be in the future.');
    expect(checkStartDate('2026-02-30')).toBe('Use the format YYYY-MM-DD, for example 2026-10-01.');
    expect(checkStartDate('01.10.2026')).toBe('Use the format YYYY-MM-DD, for example 2026-10-01.');
  });
});

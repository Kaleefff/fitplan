import { INJURY_DURATION_OPTIONS, injuryDurationLabel, monthsAgo, muscleGroupOfInjury } from '@/profile/options';
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

describe('injury duration', () => {
  const now = new Date(2026, 10, 1);

  it('turns each range into its newest day, never in the future', () => {
    expect(monthsAgo(0, now)).toBe('2026-11-01');
    expect(monthsAgo(1, now)).toBe('2026-10-01');
    expect(monthsAgo(12, now)).toBe('2025-11-01');
    expect(monthsAgo(36, now)).toBe('2023-11-01');
  });

  it('reads back the range the user chose', () => {
    for (const option of INJURY_DURATION_OPTIONS) {
      expect(injuryDurationLabel(monthsAgo(option.value, now), now)).toBe(option.label);
    }
  });

  it('survives a month shorter than today’s day', () => {
    const endOfMarch = new Date(2026, 2, 31);
    expect(monthsAgo(1, endOfMarch) <= monthsAgo(0, endOfMarch)).toBe(true);
    expect(injuryDurationLabel(monthsAgo(1, endOfMarch), endOfMarch)).toBe('1–12 months');
  });
});

describe('muscle group of an injury', () => {
  it('follows from a type that names a part of the body', () => {
    expect(muscleGroupOfInjury('Knee pain')).toBe('quadriceps');
    expect(muscleGroupOfInjury('Ankle sprain')).toBe('calves');
  });

  it('is left to the user for a type that does not', () => {
    expect(muscleGroupOfInjury('Fracture')).toBeNull();
    expect(muscleGroupOfInjury('Wrist sprain')).toBeNull();
  });
});

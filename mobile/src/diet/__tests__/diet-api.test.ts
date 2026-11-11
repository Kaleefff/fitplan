import { dayIndexOn } from '@/diet/diet-api';
import { grams } from '@/diet/labels';

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

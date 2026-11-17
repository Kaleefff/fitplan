import {
  compactNumber,
  describePrediction,
  formatValue,
  getAnalytics,
  niceTicks,
  shortDate,
  signedKg,
  type GoalPrediction,
} from '@/analytics/analytics-api';

const mockGet = jest.fn();
jest.mock('@/api/client', () => ({
  api: { GET: (...args: unknown[]) => mockGet(...args) },
  unwrap: (call: Promise<unknown>) => call,
}));

const prediction = (extra: Partial<GoalPrediction>): GoalPrediction => ({
  status: 'ok',
  estimated_date: null,
  slope_kg_per_week: null,
  r_squared: null,
  warnings: [],
  irregular_data: false,
  ...extra,
});

describe('analytics formatting', () => {
  it('signs weight changes', () => {
    expect(signedKg(1.24)).toBe('+1.2 kg');
    expect(signedKg(-0.46)).toBe('−0.5 kg');
    expect(signedKg(0.04)).toBe('0 kg');
  });

  it('compacts large numbers from 10 000', () => {
    expect(compactNumber(1284)).toBe('1,284');
    expect(compactNumber(12940)).toBe('12.9K');
    expect(compactNumber(2450.6)).toBe('2,451');
  });

  it('prints each chart value in its unit', () => {
    expect(formatValue('weight', 80.25)).toBe('80.3 kg');
    expect(formatValue('workouts_per_week', 1)).toBe('1 workout');
    expect(formatValue('workouts_per_week', 3)).toBe('3 workouts');
    expect(formatValue('calories', 2450)).toBe('2,450 kcal');
    expect(formatValue('tonnage', 14200)).toBe('14.2K kg');
  });

  it('reads dates as calendar days', () => {
    expect(shortDate('2026-11-02')).toBe('2 Nov');
    expect(shortDate('2027-01-31')).toBe('31 Jan');
  });

  it('puts axis ticks on round numbers', () => {
    expect(niceTicks(78.4, 80.9)).toEqual([78, 79, 80, 81]);
    expect(niceTicks(79.6, 80.2)).toEqual([79.6, 79.8, 80, 80.2]);
    expect(niceTicks(0, 3)).toEqual([0, 1, 2, 3]);
    expect(niceTicks(0, 2450)).toEqual([0, 1000, 2000, 3000]);
    // One value still gives a range around it
    expect(niceTicks(80, 80).length).toBeGreaterThan(1);
  });
});

describe('goal prediction text (algorithms.md 9)', () => {
  it('gives the date and the weekly trend', () => {
    const text = describePrediction(
      prediction({ estimated_date: '2026-12-11', slope_kg_per_week: -0.49, r_squared: 1 }),
    );
    expect(text.title).toBe('You may reach your target weight around 11 Dec 2026');
    expect(text.detail).toBe('Trend: −0.5 kg per week.');
  });

  it('explains every warning of irregular data', () => {
    const text = describePrediction(
      prediction({
        estimated_date: '2027-02-21',
        slope_kg_per_week: -0.26,
        warnings: ['low_fit', 'low_training_compliance'],
        irregular_data: true,
      }),
    );
    expect(text.warnings).toEqual([
      'Your weigh-ins vary a lot, so the trend is not a good fit.',
      'You did less than 60 % of your planned workouts in the last 4 weeks.',
    ]);
  });

  it('has a text for every status', () => {
    expect(describePrediction(prediction({ status: 'no_target' })).title).toBe('No target weight');
    expect(describePrediction(prediction({ status: 'insufficient_data' })).title).toBe('Not enough weigh-ins yet');
    expect(describePrediction(prediction({ status: 'goal_reached' })).title).toBe(
      'You have reached your target weight',
    );
    expect(describePrediction(prediction({ status: 'no_progress' })).title).toBe('Your weight is not changing');
    expect(describePrediction(prediction({ status: 'moving_away', slope_kg_per_week: 0.3 })).detail).toBe(
      'Trend: +0.3 kg per week.',
    );
  });
});

describe('getAnalytics', () => {
  it('asks for the summary, the prediction and every chart of the period', async () => {
    mockGet.mockImplementation((path: string, options?: { params: { path?: { metric: string } } }) =>
      Promise.resolve(
        path === '/analytics/charts/{metric}'
          ? { status: 'ok', metric: options!.params.path!.metric, period: 'month', points: [] }
          : { status: 'ok' },
      ),
    );

    const data = await getAnalytics('month');

    expect(mockGet).toHaveBeenCalledWith('/analytics/summary', { params: { query: { period: 'month' } } });
    expect(mockGet).toHaveBeenCalledWith('/analytics/goal-prediction');
    expect(mockGet).toHaveBeenCalledWith('/analytics/charts/{metric}', {
      params: { path: { metric: 'tonnage' }, query: { period: 'month' } },
    });
    expect(Object.keys(data.charts).sort()).toEqual([
      'calories',
      'diet_compliance',
      'tonnage',
      'weight',
      'workout_compliance',
      'workouts_per_week',
    ]);
  });
});

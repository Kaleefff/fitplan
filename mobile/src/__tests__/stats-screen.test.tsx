import { fireEvent, screen } from '@testing-library/react-native';
import { useEffect } from 'react';

import type { Analytics, ChartMetric, ChartPoint } from '@/analytics/analytics-api';
import { ApiError } from '@/api/errors';
import StatsScreen from '@/app/(tabs)/stats';
import { renderWithTheme } from '@/test-utils';

const mockUseEffect = useEffect;
jest.mock('expo-router', () => ({
  // Runs again when its dependencies change, as the real hook does on focus
  useFocusEffect: (effect: () => void) => mockUseEffect(effect, [effect]),
}));

const mockGetAnalytics = jest.fn();
jest.mock('@/analytics/analytics-api', () => ({
  ...jest.requireActual('@/analytics/analytics-api'),
  getAnalytics: (...args: unknown[]) => mockGetAnalytics(...args),
}));

const series = (metric: ChartMetric, points: ChartPoint[]) => ({
  status: 'ok' as const,
  metric,
  period: 'week' as const,
  points,
});

function analytics(
  extra: Partial<Analytics['summary']> = {},
  prediction: Partial<Analytics['prediction']> = {},
): Analytics {
  return {
    summary: {
      status: 'ok',
      period: 'week',
      period_start: '2026-11-11',
      period_end: '2026-11-17',
      weight_change: -0.6,
      total_workouts: 3,
      avg_workouts_per_week: 3,
      avg_calories: 2450.4,
      tonnage: 12940,
      workout_compliance_pct: 100,
      diet_compliance_pct: 57.1,
      key_lifts: [{ exercise_id: 5, exercise_name: 'Barbell back squat', first_e1rm: 80, best_e1rm: 85.3 }],
      ...extra,
    },
    prediction: {
      status: 'ok',
      estimated_date: '2027-01-20',
      slope_kg_per_week: -0.4,
      r_squared: 0.3,
      warnings: ['low_fit'],
      irregular_data: true,
      ...prediction,
    },
    charts: {
      weight: series('weight', [
        { date: '2026-11-11', value: 80.2 },
        { date: '2026-11-14', value: 79.9 },
        { date: '2026-11-17', value: 79.6 },
      ]),
      workouts_per_week: series('workouts_per_week', [
        { date: '2026-11-09', value: 2 },
        { date: '2026-11-16', value: 1 },
      ]),
      calories: series('calories', []),
      tonnage: series('tonnage', [{ date: '2026-11-12', value: 4200 }]),
    },
  };
}

describe('StatsScreen', () => {
  beforeEach(() => jest.clearAllMocks());

  it('shows the tiles, the prediction, key lifts and the charts of the week (M-18)', async () => {
    mockGetAnalytics.mockResolvedValue(analytics());
    await renderWithTheme(<StatsScreen />);

    expect(await screen.findByLabelText('Weight change: −0.6 kg')).toBeOnTheScreen();
    expect(mockGetAnalytics).toHaveBeenCalledWith('week');
    expect(screen.getByLabelText('Average calories: 2,450 kcal')).toBeOnTheScreen();
    expect(screen.getByLabelText('Tonnage: 12.9K kg')).toBeOnTheScreen();
    expect(screen.getByLabelText('Diet days on target: 57.1 %')).toBeOnTheScreen();
    expect(screen.getByText('You may reach your target weight around 20 Jan 2027')).toBeOnTheScreen();
    expect(screen.getByText('Irregular data: the date is only a rough guess')).toBeOnTheScreen();
    expect(screen.getByText('80 → 85.3 kg')).toBeOnTheScreen();
    expect(screen.getByText('Last: 79.6 kg on 17 Nov')).toBeOnTheScreen();
    // Calories have no points this week
    expect(screen.getByText('No data in this period.')).toBeOnTheScreen();
  });

  it('describes each chart for screen readers and lists its values in a table', async () => {
    mockGetAnalytics.mockResolvedValue(analytics());
    await renderWithTheme(<StatsScreen />);

    const chart = await screen.findByLabelText(
      'Weight: 3 values from 11 Nov to 17 Nov. Lowest 79.6 kg, highest 80.2 kg, last 79.6 kg.',
    );
    await fireEvent(chart, 'layout', { nativeEvent: { layout: { width: 300 } } });
    // A tap at the left edge picks the first weigh-in
    await fireEvent.press(chart, { nativeEvent: { locationX: 44 } });
    expect(screen.getByText('11 Nov: 80.2 kg')).toBeOnTheScreen();

    await fireEvent.press(screen.getAllByRole('button', { name: 'Show as table' })[0]);
    expect(screen.getByText('14 Nov')).toBeOnTheScreen();
    expect(screen.getByText('79.9 kg')).toBeOnTheScreen();
  });

  it('loads the chosen period', async () => {
    mockGetAnalytics.mockResolvedValue(analytics());
    await renderWithTheme(<StatsScreen />);
    await screen.findByLabelText('Weight change: −0.6 kg');

    mockGetAnalytics.mockResolvedValue(analytics({ period: 'month', total_workouts: 11 }));
    await fireEvent.press(screen.getByRole('radio', { name: 'Month' }));

    expect(await screen.findByLabelText('Workouts: 11')).toBeOnTheScreen();
    expect(mockGetAnalytics).toHaveBeenLastCalledWith('month');
  });

  it('says when there is not enough data (FR-R5)', async () => {
    mockGetAnalytics.mockResolvedValue(analytics({ status: 'insufficient_data' }));
    await renderWithTheme(<StatsScreen />);

    expect(await screen.findByText('Not enough data yet')).toBeOnTheScreen();
    expect(screen.queryByText('Goal prediction')).not.toBeOnTheScreen();
  });

  it('shows a dash for a metric without data and no warning for regular data', async () => {
    mockGetAnalytics.mockResolvedValue(
      analytics({ weight_change: null, key_lifts: [] }, { warnings: [], irregular_data: false }),
    );
    await renderWithTheme(<StatsScreen />);

    expect(await screen.findByLabelText('Weight change: –')).toBeOnTheScreen();
    expect(screen.queryByText('Irregular data: the date is only a rough guess')).not.toBeOnTheScreen();
    expect(screen.queryByText('Key lifts')).not.toBeOnTheScreen();
  });

  it('tries again after a connection problem', async () => {
    mockGetAnalytics
      .mockRejectedValueOnce(new ApiError(0, 'network_error', 'offline', []))
      .mockResolvedValue(analytics());
    await renderWithTheme(<StatsScreen />);

    await fireEvent.press(await screen.findByRole('button', { name: 'Try again' }));
    expect(await screen.findByLabelText('Weight change: −0.6 kg')).toBeOnTheScreen();
  });
});

import { api, unwrap } from '@/api/client';
import type { components } from '@/api/schema';

type Schemas = components['schemas'];
export type AnalyticsSummary = Schemas['AnalyticsSummary'];
export type ChartSeries = Schemas['ChartSeries'];
export type ChartPoint = Schemas['ChartPoint'];
export type GoalPrediction = Schemas['GoalPrediction'];
export type Period = AnalyticsSummary['period'];
export type ChartMetric = ChartSeries['metric'];

export const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: '3months', label: '3 Months' },
];

export function getSummary(period: Period): Promise<AnalyticsSummary> {
  return unwrap(api.GET('/analytics/summary', { params: { query: { period } } }));
}

export function getChart(metric: ChartMetric, period: Period): Promise<ChartSeries> {
  return unwrap(
    api.GET('/analytics/charts/{metric}', {
      params: { path: { metric }, query: { period } },
    }),
  );
}

export function getGoalPrediction(): Promise<GoalPrediction> {
  return unwrap(api.GET('/analytics/goal-prediction'));
}

/** Everything the screen shows for one period, fetched at once */
export type Analytics = {
  summary: AnalyticsSummary;
  charts: Record<ChartMetric, ChartSeries>;
  prediction: GoalPrediction;
};

export const CHART_METRICS: ChartMetric[] = ['weight', 'workouts_per_week', 'calories', 'tonnage'];

export async function getAnalytics(period: Period): Promise<Analytics> {
  const [summary, prediction, ...series] = await Promise.all([
    getSummary(period),
    getGoalPrediction(),
    ...CHART_METRICS.map((metric) => getChart(metric, period)),
  ]);
  const charts = Object.fromEntries(series.map((s) => [s.metric, s])) as Record<ChartMetric, ChartSeries>;
  return { summary, charts, prediction };
}

// ---------------------------------------------------------------- formatting

/** 1 decimal at most, no trailing zero: 80 -> "80", 80.25 -> "80.3" (half up as the API rounds) */
export function oneDecimal(value: number): string {
  return String(Math.round(value * 10) / 10);
}

/** 1284 -> "1,284"; 12 900 -> "12.9K" (dataviz: compact from 10 000) */
export function compactNumber(value: number): string {
  if (Math.abs(value) >= 10000) {
    return `${oneDecimal(value / 1000)}K`;
  }
  return Math.round(value).toLocaleString('en-US');
}

/** "+1.2 kg", "−0.5 kg", "0 kg" */
export function signedKg(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '';
  return `${sign}${oneDecimal(Math.abs(rounded))} kg`;
}

/** "12 Nov" from an ISO date, read as a calendar date (no time zone shift) */
export function shortDate(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });
}

/** The values of a chart in its unit: "80.2 kg", "3 workouts", "2,450 kcal", "4,200 kg" */
export function formatValue(metric: ChartMetric, value: number): string {
  switch (metric) {
    case 'weight':
      return `${oneDecimal(value)} kg`;
    case 'workouts_per_week':
      return `${oneDecimal(value)} ${value === 1 ? 'workout' : 'workouts'}`;
    case 'calories':
      return `${compactNumber(value)} kcal`;
    case 'tonnage':
      return `${compactNumber(value)} kg`;
    default:
      return `${oneDecimal(value)} %`;
  }
}

export const CHART_TITLES: Record<ChartMetric, { title: string; subtitle: string }> = {
  weight: { title: 'Weight', subtitle: 'Each weigh-in, kg' },
  workouts_per_week: {
    title: 'Workouts per week',
    subtitle: 'Week starting on Monday',
  },
  calories: {
    title: 'Calories',
    subtitle: 'Each day with a logged meal, kcal',
  },
  tonnage: {
    title: 'Tonnage',
    subtitle: 'Reps × weight of completed sets, each workout day',
  },
};

const WARNINGS: Record<GoalPrediction['warnings'][number], string> = {
  low_fit: 'Your weigh-ins vary a lot, so the trend is not a good fit.',
  gaps: 'There are more than 10 days between some weigh-ins.',
  low_training_compliance: 'You did less than 60 % of your planned workouts in the last 4 weeks.',
};

/** What the goal prediction card says (algorithms.md 9) */
export function describePrediction(prediction: GoalPrediction): {
  title: string;
  detail: string | null;
  warnings: string[];
} {
  const slope =
    prediction.slope_kg_per_week !== null && prediction.slope_kg_per_week !== undefined
      ? `Trend: ${signedKg(prediction.slope_kg_per_week)} per week.`
      : null;
  const warnings = prediction.warnings.map((w) => WARNINGS[w]);
  switch (prediction.status) {
    case 'ok':
      return {
        title: prediction.estimated_date
          ? `You may reach your target weight around ${shortDate(prediction.estimated_date)} ${prediction.estimated_date.slice(0, 4)}`
          : 'You are moving towards your target weight',
        detail: slope,
        warnings,
      };
    case 'goal_reached':
      return {
        title: 'You have reached your target weight',
        detail: slope,
        warnings,
      };
    case 'no_target':
      return {
        title: 'No target weight',
        detail: 'Set a target weight in your profile to see a prediction.',
        warnings,
      };
    case 'insufficient_data':
      return {
        title: 'Not enough weigh-ins yet',
        detail: 'The prediction needs at least 3 weigh-ins over 7 days or more in the last 4 weeks.',
        warnings,
      };
    case 'no_progress':
      return { title: 'Your weight is not changing', detail: slope, warnings };
    case 'moving_away':
      return {
        title: 'Your weight is moving away from your target',
        detail: slope,
        warnings,
      };
    default:
      return { title: 'No prediction', detail: null, warnings };
  }
}

// ---------------------------------------------------------------- chart scales

/** Clean axis ticks around [min, max]: steps of 1, 2 or 5 × 10^n (dataviz: round tick values) */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) {
    const pad = Math.abs(min) > 0 ? Math.abs(min) * 0.05 : 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw)!;
  // The small tolerance keeps 79.6 / 0.2 = 397.999… from adding a tick below the data
  const first = Math.floor(min / step + 1e-9) * step;
  const last = Math.ceil(max / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let t = first; t <= last + step / 2; t += step) {
    ticks.push(Math.round(t / step) * step);
  }
  // Removes float noise such as 0.30000000000000004
  return ticks.map((t) => Number(t.toPrecision(12)));
}

/** Days between two ISO dates, as calendar days */
export function dayNumber(iso: string): number {
  const [year, month, day] = iso.split('-').map(Number);
  return Date.UTC(year, month - 1, day) / 86400000;
}

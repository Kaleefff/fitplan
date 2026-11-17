import Ionicons from '@expo/vector-icons/Ionicons';
import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import {
  CHART_METRICS,
  CHART_TITLES,
  compactNumber,
  describePrediction,
  formatValue,
  getAnalytics,
  hasValues,
  oneDecimal,
  PERIOD_OPTIONS,
  signedKg,
  type Analytics,
  type AnalyticsSummary,
  type ChartMetric,
  type Period,
} from '@/analytics/analytics-api';
import { TimeChart } from '@/analytics/time-chart';
import { toApiError, userMessage } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { MetricTile } from '@/components/metric-tile';
import { OptionGroup } from '@/components/option-group';
import { Screen } from '@/components/screen';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { ColorName } from '@/theme/tokens';

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: Analytics };

const CHART_STYLE: Record<ChartMetric, { kind: 'line' | 'bar'; color: ColorName; stepDays: number; axisMax?: number }> =
  {
    weight: { kind: 'line', color: 'chartAnalytics', stepDays: 1 },
    workouts_per_week: { kind: 'bar', color: 'chartAnalytics', stepDays: 7 },
    calories: { kind: 'bar', color: 'chartKcal', stepDays: 1 },
    tonnage: { kind: 'bar', color: 'chartAnalytics', stepDays: 1 },
    workout_compliance: { kind: 'bar', color: 'chartAnalytics', stepDays: 7, axisMax: 100 },
    diet_compliance: { kind: 'bar', color: 'chartKcal', stepDays: 7, axisMax: 100 },
  };

const orDash = (value: number | null | undefined, show: (value: number) => string) =>
  value === null || value === undefined ? '–' : show(value);

function Tiles({ summary }: { summary: AnalyticsSummary }) {
  const { spacing } = useAppTheme();
  return (
    <View style={[styles.tiles, { gap: spacing.md }]}>
      <MetricTile
        icon="scale-outline"
        color="analytics"
        label="Weight change"
        value={orDash(summary.weight_change, signedKg)}
      />
      <MetricTile
        icon="barbell-outline"
        color="training"
        label="Workouts"
        value={orDash(summary.total_workouts, String)}
      />
      <MetricTile
        icon="calendar-outline"
        color="training"
        label="Workouts per week"
        value={orDash(summary.avg_workouts_per_week, oneDecimal)}
      />
      <MetricTile
        icon="flame-outline"
        color="kcal"
        label="Average calories"
        value={orDash(summary.avg_calories, (v) => `${compactNumber(v)} kcal`)}
      />
      <MetricTile
        icon="trending-up-outline"
        color="analytics"
        label="Tonnage"
        value={orDash(summary.tonnage, (v) => `${compactNumber(v)} kg`)}
      />
      <MetricTile
        icon="checkmark-done-outline"
        color="success"
        label="Workout plan done"
        value={orDash(summary.workout_compliance_pct, (v) => `${oneDecimal(v)} %`)}
      />
      <MetricTile
        icon="nutrition-outline"
        color="diet"
        label="Diet days on target"
        value={orDash(summary.diet_compliance_pct, (v) => `${oneDecimal(v)} %`)}
      />
    </View>
  );
}

function PredictionCard({ data }: { data: Analytics }) {
  const { colors, spacing } = useAppTheme();
  const text = describePrediction(data.prediction);
  return (
    <Card style={{ gap: spacing.sm }}>
      <AppText variant="caption" color="textMuted">
        Goal prediction
      </AppText>
      <AppText variant="title">{text.title}</AppText>
      {text.detail ? <AppText color="textMuted">{text.detail}</AppText> : null}
      {data.prediction.irregular_data ? (
        <View
          style={[
            styles.warning,
            {
              gap: spacing.sm,
              borderColor: colors.warning,
              padding: spacing.md,
            },
          ]}
          accessibilityRole="alert">
          <Ionicons name="warning-outline" size={20} color={colors.warning} />
          <View style={[styles.fill, { gap: spacing.xs }]}>
            <AppText variant="bodyStrong">Irregular data: the date is only a rough guess</AppText>
            {text.warnings.map((warning) => (
              <AppText key={warning} color="textMuted">
                {warning}
              </AppText>
            ))}
          </View>
        </View>
      ) : null}
    </Card>
  );
}

function KeyLifts({ summary }: { summary: AnalyticsSummary }) {
  const { spacing } = useAppTheme();
  const lifts = summary.key_lifts ?? [];
  if (lifts.length === 0) {
    return null;
  }
  return (
    <Card style={{ gap: spacing.sm }}>
      <AppText variant="title">Key lifts</AppText>
      <AppText variant="caption" color="textMuted">
        Estimated one-rep max (e1RM): first in this period → best
      </AppText>
      {lifts.map((lift) => (
        <View key={lift.exercise_id} style={styles.row} accessible>
          <AppText style={styles.fill}>{lift.exercise_name}</AppText>
          <AppText variant="bodyStrong">
            {oneDecimal(lift.first_e1rm)} → {oneDecimal(lift.best_e1rm)} kg
          </AppText>
        </View>
      ))}
    </Card>
  );
}

function ChartCard({ metric, data }: { metric: ChartMetric; data: Analytics }) {
  const series = data.charts[metric];
  const { title, subtitle } = CHART_TITLES[metric];
  const style = CHART_STYLE[metric];
  return (
    <Card>
      <AppText variant="title" accessibilityRole="header">
        {title}
      </AppText>
      <AppText variant="caption" color="textMuted">
        {subtitle}
      </AppText>
      {!hasValues(series.points) ? (
        <AppText color="textMuted">No data in this period.</AppText>
      ) : (
        <TimeChart
          title={title}
          points={series.points}
          kind={style.kind}
          color={style.color}
          stepDays={style.stepDays}
          axisMax={style.axisMax}
          from={data.summary.period_start}
          to={data.summary.period_end}
          format={(value) => formatValue(metric, value)}
        />
      )}
    </Card>
  );
}

// Analytics (M-18, FR-R1–R5): metric tiles, compliance, goal prediction and charts for a period
export default function StatsScreen() {
  const [period, setPeriod] = useState<Period>('week');
  const [load, setLoad] = useState<Load>({ status: 'loading' });

  const fetchPeriod = useCallback(async (next: Period) => {
    try {
      setLoad({ status: 'ready', data: await getAnalytics(next) });
    } catch (error) {
      setLoad({ status: 'error', message: userMessage(toApiError(error)) });
    }
  }, []);

  // Reloads when the tab is opened: a workout, a meal or a weigh-in may have been added
  useFocusEffect(
    useCallback(() => {
      fetchPeriod(period);
    }, [fetchPeriod, period]),
  );

  const choose = (next: Period) => {
    if (next !== period) {
      setLoad({ status: 'loading' });
      setPeriod(next);
    }
  };

  return (
    <Screen>
      <OptionGroup label="Period" options={PERIOD_OPTIONS} value={period} onChange={choose} />

      {load.status === 'loading' ? <ActivityIndicator accessibilityLabel="Loading your analytics" /> : null}
      {load.status === 'error' ? (
        <>
          <FormMessage message={load.message} />
          <Button
            title="Try again"
            onPress={() => {
              setLoad({ status: 'loading' });
              fetchPeriod(period);
            }}
          />
        </>
      ) : null}

      {load.status === 'ready' && load.data.summary.status === 'insufficient_data' ? (
        <Card>
          <AppText variant="title">Not enough data yet</AppText>
          <AppText color="textMuted">
            Analytics start after 7 days with any record: a workout, a logged meal or a weigh-in. Keep logging and come
            back soon.
          </AppText>
        </Card>
      ) : null}

      {load.status === 'ready' && load.data.summary.status === 'ok' ? (
        <>
          <Tiles summary={load.data.summary} />
          <PredictionCard data={load.data} />
          <KeyLifts summary={load.data.summary} />
          {CHART_METRICS.map((metric) => (
            <ChartCard key={metric} metric={metric} data={load.data} />
          ))}
        </>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  tiles: { flexDirection: 'row', flexWrap: 'wrap' },
  warning: { flexDirection: 'row', borderWidth: 1, borderRadius: 8 },
  row: { flexDirection: 'row', alignItems: 'center' },
  fill: { flex: 1 },
});

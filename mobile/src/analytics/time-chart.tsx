import { useState } from 'react';
import { Pressable, StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';

import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { ColorName } from '@/theme/tokens';
import { dayNumber, niceTicks, shortDate, type ChartPoint } from '@/analytics/analytics-api';

const HEIGHT = 180;
const AXIS_LEFT = 44;
const AXIS_BOTTOM = 22;
const TOP = 8;
const RIGHT = 8;
// dataviz mark specs
const MAX_BAR = 24;
const BAR_RADIUS = 4;
const MARKER_RADIUS = 4;
const RING = 2;
/** Above this many points the line shows only its last marker */
const MAX_MARKERS = 31;

type TimeChartProps = {
  /** Read by screen readers before the values, for example "Weight" */
  title: string;
  points: ChartPoint[];
  kind: 'line' | 'bar';
  color: ColorName;
  /** First and last day of the period */
  from: string;
  to: string;
  /** Days one bar stands for: 1 per day, 7 per week (keeps bars inside the plot) */
  stepDays?: number;
  format: (value: number) => string;
};

/** Path of a bar with 4 px rounded corners at its data end and a square baseline */
function barPath(x: number, y: number, width: number, height: number): string {
  const r = Math.min(BAR_RADIUS, width / 2, height);
  return [
    `M${x},${y + height}`,
    `V${y + r}`,
    `Q${x},${y} ${x + r},${y}`,
    `H${x + width - r}`,
    `Q${x + width},${y} ${x + width},${y + r}`,
    `V${y + height}`,
    'Z',
  ].join(' ');
}

/** One series over time; tap it to read a value, or open the table (dataviz: single series, no legend) */
export function TimeChart({ title, points, kind, color, from, to, stepDays = 1, format }: TimeChartProps) {
  const { colors, spacing } = useAppTheme();
  const [width, setWidth] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [table, setTable] = useState(false);

  const sorted = [...points].sort((a, b) => dayNumber(a.date) - dayNumber(b.date));
  const values = sorted.map((p) => p.value);
  const low = Math.min(...values);
  const high = Math.max(...values);
  // Bars grow from zero; a weight line is read for its change, so its axis fits the values
  const ticks = kind === 'bar' ? niceTicks(0, Math.max(high, 1)) : niceTicks(low, high);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];

  const half = kind === 'bar' ? stepDays / 2 : 0;
  const start = Math.min(dayNumber(from), ...sorted.map((p) => dayNumber(p.date))) - half;
  const end = Math.max(dayNumber(to), ...sorted.map((p) => dayNumber(p.date))) + half;
  const plotWidth = Math.max(width - AXIS_LEFT - RIGHT, 1);
  const plotHeight = HEIGHT - TOP - AXIS_BOTTOM;
  const x = (iso: string) => AXIS_LEFT + ((dayNumber(iso) - start) / Math.max(end - start, 1)) * plotWidth;
  const y = (value: number) => TOP + (1 - (value - yMin) / Math.max(yMax - yMin, 1e-9)) * plotHeight;

  const xs = sorted.map((p) => x(p.date));
  const gaps = xs.slice(1).map((value, i) => value - xs[i]);
  const slot = Math.min(plotWidth / Math.max(sorted.length, 1), ...gaps);
  const barWidth = Math.max(3, Math.min(MAX_BAR, slot - 2));

  const pick = (locationX: number) => {
    let best = 0;
    xs.forEach((value, i) => {
      if (Math.abs(value - locationX) < Math.abs(xs[best] - locationX)) best = i;
    });
    setSelected(best === selected ? null : best);
  };

  const point = selected !== null ? sorted[selected] : null;
  const last = sorted[sorted.length - 1];
  const summary =
    `${title}: ${sorted.length} ${sorted.length === 1 ? 'value' : 'values'} from ${shortDate(sorted[0].date)} ` +
    `to ${shortDate(last.date)}. Lowest ${format(low)}, highest ${format(high)}, last ${format(last.value)}.`;

  return (
    <View style={{ gap: spacing.sm }}>
      <AppText variant="caption" color="textMuted" accessibilityLiveRegion="polite">
        {point
          ? `${shortDate(point.date)}: ${format(point.value)}`
          : `Last: ${format(last.value)} on ${shortDate(last.date)}`}
      </AppText>
      <Pressable
        onLayout={(event: LayoutChangeEvent) => setWidth(event.nativeEvent.layout.width)}
        onPress={(event) => pick(event.nativeEvent.locationX)}
        accessibilityRole="image"
        accessibilityLabel={summary}
        accessibilityHint="Tap the chart to read a value. The table lists all values."
        style={styles.plot}>
        {width > 0 ? (
          <Svg width={width} height={HEIGHT}>
            {ticks.map((tick) => (
              <Line
                key={`grid-${tick}`}
                x1={AXIS_LEFT}
                x2={width - RIGHT}
                y1={y(tick)}
                y2={y(tick)}
                stroke={colors.border}
                strokeWidth={1}
              />
            ))}
            {ticks.map((tick) => (
              <SvgText
                key={`tick-${tick}`}
                x={AXIS_LEFT - 6}
                y={y(tick) + 4}
                fontSize={11}
                fill={colors.textMuted}
                textAnchor="end">
                {Math.abs(tick) >= 10000 ? `${tick / 1000}K` : tick.toLocaleString('en-US')}
              </SvgText>
            ))}
            <SvgText x={AXIS_LEFT} y={HEIGHT - 6} fontSize={11} fill={colors.textMuted} textAnchor="start">
              {shortDate(from)}
            </SvgText>
            <SvgText x={width - RIGHT} y={HEIGHT - 6} fontSize={11} fill={colors.textMuted} textAnchor="end">
              {shortDate(to)}
            </SvgText>

            {point ? (
              <Line
                x1={xs[selected!]}
                x2={xs[selected!]}
                y1={TOP}
                y2={TOP + plotHeight}
                stroke={colors.textMuted}
                strokeWidth={1}
              />
            ) : null}

            {kind === 'bar'
              ? sorted.map((p, i) => {
                  const top = y(Math.max(p.value, 0));
                  const height = Math.max(y(0) - top, p.value > 0 ? 1 : 0);
                  return height > 0 ? (
                    <Path
                      key={p.date}
                      d={barPath(xs[i] - barWidth / 2, top, barWidth, height)}
                      fill={colors[color]}
                      opacity={selected === null || selected === i ? 1 : 0.45}
                    />
                  ) : null;
                })
              : null}

            {kind === 'line' ? (
              <>
                <Path
                  d={sorted.map((p, i) => `${i === 0 ? 'M' : 'L'}${xs[i]},${y(p.value)}`).join(' ')}
                  stroke={colors[color]}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  fill="none"
                />
                {sorted.map((p, i) =>
                  sorted.length <= MAX_MARKERS || i === sorted.length - 1 || i === selected ? (
                    <Circle
                      key={p.date}
                      cx={xs[i]}
                      cy={y(p.value)}
                      r={i === selected ? MARKER_RADIUS + 1 : MARKER_RADIUS}
                      fill={colors[color]}
                      stroke={colors.surface}
                      strokeWidth={RING}
                    />
                  ) : null,
                )}
              </>
            ) : null}
          </Svg>
        ) : null}
      </Pressable>

      <Button
        title={table ? 'Hide table' : 'Show as table'}
        variant="ghost"
        onPress={() => setTable((open) => !open)}
      />
      {table ? (
        <View accessibilityLabel={`${title} values`}>
          {sorted.map((p) => (
            <View key={p.date} style={[styles.row, { borderColor: colors.border, paddingVertical: spacing.xs }]}>
              <AppText style={styles.fill}>{shortDate(p.date)}</AppText>
              <AppText>{format(p.value)}</AppText>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  plot: { height: HEIGHT, width: '100%' },
  row: { flexDirection: 'row', borderBottomWidth: StyleSheet.hairlineWidth },
  fill: { flex: 1 },
});

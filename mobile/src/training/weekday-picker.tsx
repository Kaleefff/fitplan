import { View } from 'react-native';

import { AppText } from '@/components/app-text';
import { MultiOptionGroup } from '@/components/option-group';
import { useAppTheme } from '@/hooks/use-app-theme';
import { describeSplit } from '@/training/schedule';
import { WEEKDAYS_SHORT } from '@/utils/dates';

const WEEKDAY_OPTIONS = [1, 2, 3, 4, 5, 6, 7].map((day) => ({ value: day, label: WEEKDAYS_SHORT[day] }));

type WeekdayPickerProps = {
  label: string;
  values: number[];
  onChange: (weekdays: number[]) => void;
  error?: string;
};

/** Weekdays to train on (1 = Monday), with the sessions of the split each one gets (algorithms.md 4.5) */
export function WeekdayPicker({ label, values, onChange, error }: WeekdayPickerProps) {
  const { spacing } = useAppTheme();
  return (
    <View style={{ gap: spacing.xs }}>
      <MultiOptionGroup
        label={label}
        options={WEEKDAY_OPTIONS}
        values={values}
        onChange={(next) => onChange([...next].sort((a, b) => a - b))}
        error={error}
      />
      {values.length > 0 ? (
        <AppText variant="caption" color="textMuted">
          {values.length} {values.length === 1 ? 'day' : 'days'} a week · {describeSplit(values)}
        </AppText>
      ) : null}
    </View>
  );
}

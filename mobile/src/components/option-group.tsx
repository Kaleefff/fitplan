import type { ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';

export type Option<T> = {
  value: T;
  label: string;
  /** Second line under the label, for example "1.2" under "Sedentary" */
  hint?: string;
};

type ChipProps = {
  label: string;
  hint?: string;
  selected: boolean;
  onPress: () => void;
  multiple: boolean;
};

function Chip({ label, hint, selected, onPress, multiple }: ChipProps) {
  const { colors, radius, spacing } = useAppTheme();
  return (
    <Pressable
      accessibilityRole={multiple ? 'checkbox' : 'radio'}
      accessibilityState={multiple ? { checked: selected } : { selected }}
      accessibilityLabel={hint ? `${label}, ${hint}` : label}
      onPress={onPress}
      style={({ pressed }) => [
        styles.chip,
        {
          backgroundColor: selected ? colors.primary : colors.surface,
          borderColor: selected ? colors.primary : colors.border,
          borderRadius: radius.md,
          paddingHorizontal: spacing.md,
          opacity: pressed ? 0.7 : 1,
        },
      ]}>
      <AppText variant="bodyStrong" color={selected ? 'onPrimary' : 'text'}>
        {label}
      </AppText>
      {hint ? (
        <AppText variant="caption" color={selected ? 'onPrimary' : 'textMuted'}>
          {hint}
        </AppText>
      ) : null}
    </Pressable>
  );
}

type GroupFrameProps = {
  label: string;
  error?: string;
  multiple: boolean;
  /** Shown next to the label, for example a HelpButton */
  help?: ReactNode;
  children: ReactNode;
};

function GroupFrame({ label, error, multiple, help, children }: GroupFrameProps) {
  const { spacing } = useAppTheme();
  return (
    <View style={{ gap: spacing.xs }}>
      <View style={[styles.labelRow, { gap: spacing.sm }]}>
        <AppText variant="bodyStrong">{label}</AppText>
        {help}
      </View>
      <View
        accessibilityRole={multiple ? undefined : 'radiogroup'}
        accessibilityLabel={label}
        style={[styles.wrap, { gap: spacing.sm }]}>
        {children}
      </View>
      {error ? (
        <AppText variant="caption" color="danger" accessibilityLiveRegion="polite">
          {error}
        </AppText>
      ) : null}
    </View>
  );
}

type OptionGroupProps<T> = {
  label: string;
  options: Option<T>[];
  value: T | null;
  onChange: (value: T) => void;
  error?: string;
  help?: ReactNode;
};

/** Pick exactly one option */
export function OptionGroup<T extends string | number>({
  label,
  options,
  value,
  onChange,
  error,
  help,
}: OptionGroupProps<T>) {
  return (
    <GroupFrame label={label} error={error} multiple={false} help={help}>
      {options.map((option) => (
        <Chip
          key={String(option.value)}
          label={option.label}
          hint={option.hint}
          selected={option.value === value}
          onPress={() => onChange(option.value)}
          multiple={false}
        />
      ))}
    </GroupFrame>
  );
}

type MultiOptionGroupProps<T> = {
  label: string;
  options: Option<T>[];
  values: T[];
  onChange: (values: T[]) => void;
  error?: string;
};

/** Pick any number of options; tapping a selected one removes it */
export function MultiOptionGroup<T extends string | number>({
  label,
  options,
  values,
  onChange,
  error,
}: MultiOptionGroupProps<T>) {
  const toggle = (value: T) =>
    onChange(values.includes(value) ? values.filter((v) => v !== value) : [...values, value]);

  return (
    <GroupFrame label={label} error={error} multiple>
      {options.map((option) => (
        <Chip
          key={String(option.value)}
          label={option.label}
          hint={option.hint}
          selected={values.includes(option.value)}
          onPress={() => toggle(option.value)}
          multiple
        />
      ))}
    </GroupFrame>
  );
}

const styles = StyleSheet.create({
  labelRow: { flexDirection: 'row', alignItems: 'center' },
  wrap: { flexDirection: 'row', flexWrap: 'wrap' },
  chip: {
    minHeight: minTouchSize,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    paddingVertical: 6,
  },
});

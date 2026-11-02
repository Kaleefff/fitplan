import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Dialog } from '@/components/dialog';
import type { Option } from '@/components/option-group';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';

type SelectFieldProps<T> = {
  label: string;
  options: Option<T>[];
  value: T | null;
  onChange: (value: T) => void;
  placeholder?: string;
  error?: string;
};

/** Drop-down list: looks like a text field and opens the options in a window */
export function SelectField<T extends string | number>({
  label,
  options,
  value,
  onChange,
  placeholder = 'Choose',
  error,
}: SelectFieldProps<T>) {
  const { colors, radius, spacing } = useAppTheme();
  const [open, setOpen] = useState(false);
  const selected = options.find((option) => option.value === value);

  return (
    <View style={{ gap: spacing.xs }}>
      <AppText variant="bodyStrong">{label}</AppText>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}: ${selected?.label ?? placeholder}`}
        accessibilityHint={error}
        onPress={() => setOpen(true)}
        style={({ pressed }) => [
          styles.box,
          {
            backgroundColor: colors.surface,
            borderColor: error ? colors.danger : colors.border,
            borderRadius: radius.md,
            paddingHorizontal: spacing.md,
            opacity: pressed ? 0.7 : 1,
          },
        ]}>
        <AppText color={selected ? 'text' : 'textMuted'} style={styles.value}>
          {selected?.label ?? placeholder}
        </AppText>
        <Ionicons name="chevron-down" size={20} color={colors.textMuted} />
      </Pressable>
      {error ? (
        <AppText variant="caption" color="danger" accessibilityLiveRegion="polite">
          {error}
        </AppText>
      ) : null}

      <Dialog visible={open} title={label} onClose={() => setOpen(false)}>
        <View accessibilityRole="radiogroup" accessibilityLabel={label}>
          {options.map((option) => {
            const isSelected = option.value === value;
            return (
              <Pressable
                key={String(option.value)}
                accessibilityRole="radio"
                accessibilityState={{ selected: isSelected }}
                accessibilityLabel={option.label}
                onPress={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
                style={({ pressed }) => [styles.option, { opacity: pressed ? 0.7 : 1 }]}>
                <AppText color={isSelected ? 'primary' : 'text'} style={styles.value}>
                  {option.label}
                </AppText>
                {isSelected ? <Ionicons name="checkmark" size={20} color={colors.primary} /> : null}
              </Pressable>
            );
          })}
        </View>
      </Dialog>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { minHeight: minTouchSize, flexDirection: 'row', alignItems: 'center', borderWidth: 1, gap: 8 },
  value: { flex: 1 },
  option: { minHeight: minTouchSize, flexDirection: 'row', alignItems: 'center', gap: 8 },
});

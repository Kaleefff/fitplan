import { useCallback, useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { useAppTheme } from '@/hooks/use-app-theme';

/** Counts down the rest between sets; `remaining` is null when no rest is running */
export function useRestTimer() {
  const [endsAt, setEndsAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (endsAt === null) {
      return;
    }
    const id = setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (current >= endsAt) {
        setEndsAt(null);
      }
    }, 250);
    return () => clearInterval(id);
  }, [endsAt]);

  const start = useCallback((seconds: number) => {
    const current = Date.now();
    setNow(current);
    setEndsAt(seconds > 0 ? current + seconds * 1000 : null);
  }, []);
  const skip = useCallback(() => setEndsAt(null), []);

  const remaining = endsAt === null ? null : Math.max(0, Math.ceil((endsAt - now) / 1000));
  return { remaining, start, skip };
}

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

/** Bar under the workout while a rest runs */
export function RestBar({ remaining, onSkip }: { remaining: number; onSkip: () => void }) {
  const { colors, spacing } = useAppTheme();
  // Keeps the bar above the gesture bar of the phone
  const { bottom } = useSafeAreaInsets();
  return (
    <View
      style={[
        styles.bar,
        {
          backgroundColor: colors.surface,
          borderColor: colors.border,
          padding: spacing.md,
          paddingBottom: spacing.md + bottom,
          gap: spacing.md,
        },
      ]}>
      <AppText variant="title" accessibilityLiveRegion="polite" style={styles.text}>
        Rest {clock(remaining)}
      </AppText>
      <Button title="Skip rest" variant="secondary" onPress={onSkip} />
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', alignItems: 'center', borderTopWidth: 1 },
  text: { flex: 1 },
});

import { View } from 'react-native';

import { AppText } from '@/components/app-text';
import { HelpButton } from '@/components/help-button';
import { useAppTheme } from '@/hooks/use-app-theme';
import { PAL_OPTIONS } from '@/profile/options';

// The usual description of these activity multipliers; algorithms.md gives only the values
const LEVEL_DESCRIPTIONS: Record<number, string> = {
  1.2: 'Little or no exercise, mostly sitting',
  1.375: 'Light exercise 1–3 days a week',
  1.55: 'Moderate exercise 3–5 days a week',
  1.725: 'Hard exercise 6–7 days a week',
  1.9: 'Very hard exercise every day or a physical job',
};

export function PalHelp() {
  const { spacing } = useAppTheme();
  return (
    <HelpButton title="What is PAL?">
      <AppText>
        PAL (Physical Activity Level) shows how active your typical day is. It is the energy you use in a whole day
        divided by the energy your body uses at complete rest.
      </AppText>

      <View style={{ gap: spacing.xs }}>
        <AppText variant="bodyStrong">How is it measured?</AppText>
        <AppText>
          An exact measurement takes laboratory tests, so the app does not measure it. You choose the level closest to
          your typical week.
        </AppText>
      </View>

      <View style={{ gap: spacing.xs }}>
        <AppText variant="bodyStrong">What is it used for?</AppText>
        <AppText>
          Your resting energy (BMR) multiplied by PAL gives your daily energy need (TDEE). Your calorie target is based
          on it.
        </AppText>
      </View>

      <View style={{ gap: spacing.sm }}>
        <AppText variant="bodyStrong">Levels</AppText>
        {PAL_OPTIONS.map((option) => (
          <View key={option.value} accessible>
            <AppText>
              {option.label} ({option.hint})
            </AppText>
            <AppText variant="caption" color="textMuted">
              {LEVEL_DESCRIPTIONS[option.value]}
            </AppText>
          </View>
        ))}
      </View>
    </HelpButton>
  );
}

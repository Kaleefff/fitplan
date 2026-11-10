import { useState } from 'react';
import { View } from 'react-native';

import { toApiError, userMessage } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { useAppTheme } from '@/hooks/use-app-theme';
import { EQUIPMENT_OPTIONS, GOAL_OPTIONS, labelOf } from '@/profile/options';
import { readInsufficientExercises, type InsufficientExercises } from '@/training/insufficient';
import { describeSettings } from '@/training/plan-labels';
import {
  generatePlan,
  scheduleSessions,
  type PlanSettings,
  type TrainingPlan,
} from '@/training/training-api';
import { WeekdayPicker } from '@/training/weekday-picker';

type GenerateFormProps = {
  /** Goal, level and equipment of the profile; null when the profile is not loaded */
  settings: PlanSettings | null;
  /** Weekdays chosen at the start, for example those of the current plan */
  initialWeekdays: number[];
  /** `notice` says that the plan was generated but its weekdays could not be set */
  onGenerated: (plan: TrainingPlan, notice: string | null) => void;
  /** Shown as a Cancel button when there is a plan to go back to */
  onCancel?: () => void;
};

function InsufficientMessage({
  info,
  onUseEquipment,
  onUseGoal,
}: {
  info: InsufficientExercises;
  onUseEquipment: (equipment: NonNullable<InsufficientExercises['equipment']>) => void;
  onUseGoal: (goal: InsufficientExercises['goals'][number]) => void;
}) {
  const { colors, spacing } = useAppTheme();
  return (
    <Card style={{ borderColor: colors.warning, borderLeftWidth: 4 }} accessibilityRole="alert">
      <AppText variant="bodyStrong">Not enough exercises for this plan</AppText>
      {info.groups.length > 0 ? (
        <AppText>No exercise fits your level and equipment for: {info.groups.join(', ')}.</AppText>
      ) : (
        <AppText>
          Your injuries leave out every muscle group this goal needs. Update your injuries in Settings when they
          change.
        </AppText>
      )}
      {info.equipment || info.goals.length > 0 ? (
        <View style={{ gap: spacing.sm }}>
          <AppText color="textMuted">Try instead, for this plan only:</AppText>
          {info.equipment ? (
            <Button
              title={`Use ${labelOf(EQUIPMENT_OPTIONS, info.equipment).toLowerCase()} equipment`}
              variant="secondary"
              onPress={() => onUseEquipment(info.equipment!)}
            />
          ) : null}
          {info.goals.map((goal) => (
            <Button
              key={goal}
              title={`Goal: ${labelOf(GOAL_OPTIONS, goal)}`}
              variant="secondary"
              onPress={() => onUseGoal(goal)}
            />
          ))}
        </View>
      ) : null}
    </Card>
  );
}

// Generation form of FR-P1: goal, level and equipment come from the profile, the user picks the
// weekdays (their number is num_training_days, FR-P9). The 422 of FR-P3 comes back with suggestions
// that can be applied at once.
export function GenerateForm({ settings, initialWeekdays, onGenerated, onCancel }: GenerateFormProps) {
  const { spacing } = useAppTheme();
  const [weekdays, setWeekdays] = useState<number[]>(initialWeekdays);
  const [error, setError] = useState<string | undefined>(undefined);
  const [message, setMessage] = useState<string | null>(null);
  const [insufficient, setInsufficient] = useState<InsufficientExercises | null>(null);
  const [busy, setBusy] = useState(false);

  async function generate(override: Partial<PlanSettings> = {}) {
    setMessage(null);
    setInsufficient(null);
    if (weekdays.length === 0) {
      setError('Choose at least one day.');
      return;
    }
    if (!settings) {
      setMessage('Set up your profile before generating a plan.');
      return;
    }
    setBusy(true);
    try {
      const plan = await generatePlan({ ...settings, ...override, num_training_days: weekdays.length });
      try {
        onGenerated(await scheduleSessions(plan, weekdays), null);
      } catch (scheduleError) {
        onGenerated(
          plan,
          `Your plan is ready, but its days could not be changed: ${userMessage(toApiError(scheduleError))} ` +
            'Use "Change training days" to try again.',
        );
      }
    } catch (generateError) {
      const apiError = toApiError(generateError);
      const info = readInsufficientExercises(apiError);
      if (info) {
        setInsufficient(info);
      } else if (apiError.status === 404) {
        setMessage('Set up your profile before generating a plan.');
      } else {
        setMessage(userMessage(apiError));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: spacing.lg }}>
      <FormMessage message={message} />

      <Card>
        <AppText variant="bodyStrong">From your profile</AppText>
        <AppText color="textMuted">{settings ? describeSettings(settings) : 'Profile not loaded.'}</AppText>
      </Card>

      <WeekdayPicker
        label="Training days"
        values={weekdays}
        onChange={(next) => {
          setWeekdays(next);
          setError(undefined);
        }}
        error={error}
      />

      {insufficient ? (
        <InsufficientMessage
          info={insufficient}
          onUseEquipment={(equipment) => generate({ equipment })}
          onUseGoal={(goal) => generate({ goal })}
        />
      ) : null}

      <Button title="Generate plan" onPress={() => generate()} loading={busy} />
      {onCancel ? <Button title="Cancel" variant="ghost" onPress={onCancel} /> : null}
    </View>
  );
}

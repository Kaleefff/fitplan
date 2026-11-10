import { useState } from 'react';
import { View } from 'react-native';

import { fieldErrors, toApiError, userMessage } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { OptionGroup } from '@/components/option-group';
import { useAppTheme } from '@/hooks/use-app-theme';
import { EQUIPMENT_OPTIONS, GOAL_OPTIONS, labelOf, LEVEL_OPTIONS } from '@/profile/options';
import { readInsufficientExercises, type InsufficientExercises } from '@/training/insufficient';
import { generatePlan, type GenerateTrainingPlanRequest, type TrainingPlan } from '@/training/training-api';

/** What the form holds; null until chosen */
export type PlanForm = { [K in keyof GenerateTrainingPlanRequest]: GenerateTrainingPlanRequest[K] | null };

const DAY_OPTIONS = [1, 2, 3, 4, 5, 6, 7].map((days) => ({ value: days, label: String(days) }));

// Sessions and weekdays of the split, algorithms.md 4.5
const SPLITS: Record<number, string> = {
  1: 'Full Body on Wednesday',
  2: 'Full Body A and B on Monday and Thursday',
  3: 'Full Body A, B and C on Monday, Wednesday and Friday',
  4: 'Upper A, Lower A, Upper B and Lower B on Monday, Tuesday, Thursday and Friday',
  5: 'Upper, Lower, Push, Pull and Legs on Monday, Tuesday, Thursday, Friday and Saturday',
  6: 'Push, Pull and Legs twice, Monday to Saturday',
  7: 'Push, Pull and Legs twice, then Full Body, every day',
};

const CHOOSE = 'Choose an option.';

type GenerateFormProps = {
  initial: PlanForm;
  onGenerated: (plan: TrainingPlan) => void;
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
          <AppText color="textMuted">Try instead:</AppText>
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

// Generation form of FR-P1; the 422 of FR-P3 comes back with suggestions that can be applied at once
export function GenerateForm({ initial, onGenerated, onCancel }: GenerateFormProps) {
  const { spacing } = useAppTheme();
  const [form, setForm] = useState<PlanForm>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [insufficient, setInsufficient] = useState<InsufficientExercises | null>(null);
  const [busy, setBusy] = useState(false);

  function set<K extends keyof PlanForm>(field: K, value: PlanForm[K]) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  async function generate(next: PlanForm) {
    const found: Record<string, string> = {};
    for (const field of Object.keys(next) as (keyof PlanForm)[]) {
      if (next[field] === null) found[field] = CHOOSE;
    }
    setForm(next);
    setErrors(found);
    setMessage(null);
    setInsufficient(null);
    if (Object.keys(found).length > 0) {
      return;
    }
    setBusy(true);
    try {
      onGenerated(await generatePlan(next as GenerateTrainingPlanRequest));
    } catch (error) {
      const apiError = toApiError(error);
      const info = readInsufficientExercises(apiError);
      if (info) {
        setInsufficient(info);
      } else if (apiError.code === 'validation_error') {
        setErrors(fieldErrors(apiError));
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
      <OptionGroup
        label="Goal"
        options={GOAL_OPTIONS}
        value={form.goal}
        onChange={(v) => set('goal', v)}
        error={errors.goal}
      />
      <View style={{ gap: spacing.xs }}>
        <OptionGroup
          label="Training days per week"
          options={DAY_OPTIONS}
          value={form.num_training_days}
          onChange={(v) => set('num_training_days', v)}
          error={errors.num_training_days}
        />
        {form.num_training_days ? (
          <AppText variant="caption" color="textMuted">
            {SPLITS[form.num_training_days]}
          </AppText>
        ) : null}
      </View>
      <OptionGroup
        label="Training experience"
        options={LEVEL_OPTIONS}
        value={form.experience_level}
        onChange={(v) => set('experience_level', v)}
        error={errors.experience_level}
      />
      <OptionGroup
        label="Available equipment"
        options={EQUIPMENT_OPTIONS}
        value={form.equipment}
        onChange={(v) => set('equipment', v)}
        error={errors.equipment}
      />

      {insufficient ? (
        <InsufficientMessage
          info={insufficient}
          onUseEquipment={(equipment) => generate({ ...form, equipment })}
          onUseGoal={(goal) => generate({ ...form, goal })}
        />
      ) : null}

      <Button title="Generate plan" onPress={() => generate(form)} loading={busy} />
      {onCancel ? <Button title="Cancel" variant="ghost" onPress={onCancel} /> : null}
    </View>
  );
}

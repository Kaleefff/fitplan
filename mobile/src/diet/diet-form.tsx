import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { fieldErrors, toApiError, userMessage, type ApiError } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { OptionGroup } from '@/components/option-group';
import { TextField } from '@/components/text-field';
import { generateDietPlan, type DietPlan, type DietType } from '@/diet/diet-api';
import { MEAL_TYPE_LABELS } from '@/diet/labels';
import { useAppTheme } from '@/hooks/use-app-theme';

export type DietForm = { meals_per_day: number | null; diet_type: DietType; dietary_restrictions: string };

export const DIET_TYPE_OPTIONS: { value: DietType; label: string }[] = [
  { value: 'omnivore', label: 'Omnivore' },
  { value: 'vegetarian', label: 'Vegetarian' },
  { value: 'vegan', label: 'Vegan' },
];

// Meal slots and default times, algorithms.md 5.1
const MEAL_OPTIONS = [
  { value: 3, label: '3', hint: 'Breakfast 08:00, lunch 13:00, dinner 19:00' },
  { value: 4, label: '4', hint: 'Breakfast 08:00, lunch 13:00, snack 16:00, dinner 19:00' },
  { value: 5, label: '5', hint: 'Breakfast 08:00, snack 10:30, lunch 13:30, snack 16:30, dinner 19:00' },
];

const MAX_RESTRICTIONS = 500;

/** Text of a 422 `insufficient_foods` answer (algorithms.md 5.5) */
export function insufficientFoodsMessage(error: ApiError): string | null {
  if (error.code !== 'insufficient_foods') {
    return null;
  }
  const missing = (error.details as Record<string, unknown>[])
    .filter((d) => d.code === 'no_eligible_food')
    .map((d) => `${MEAL_TYPE_LABELS[d.meal_type as keyof typeof MEAL_TYPE_LABELS] ?? d.meal_type} (${d.role})`);
  if (missing.length > 0) {
    return `No food fits your diet type, allergies and excluded foods for: ${missing.join(', ')}. Try another diet type.`;
  }
  return 'The plan could not reach your daily targets with the foods that fit you. Try another diet type or number of meals.';
}

type DietFormViewProps = {
  initial: DietForm;
  onGenerated: (plan: DietPlan) => void;
  onCancel?: () => void;
};

// Generation form of FR-P6: meals per day, diet type and a free-text note
export function DietFormView({ initial, onGenerated, onCancel }: DietFormViewProps) {
  const { spacing } = useAppTheme();
  const [form, setForm] = useState<DietForm>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function generate() {
    const found: Record<string, string> = {};
    if (form.meals_per_day === null) found.meals_per_day = 'Choose an option.';
    if (form.dietary_restrictions.length > MAX_RESTRICTIONS) {
      found.dietary_restrictions = `At most ${MAX_RESTRICTIONS} characters.`;
    }
    setErrors(found);
    setMessage(null);
    if (Object.keys(found).length > 0) {
      return;
    }
    setBusy(true);
    try {
      const note = form.dietary_restrictions.trim();
      onGenerated(
        await generateDietPlan({
          meals_per_day: form.meals_per_day!,
          diet_type: form.diet_type,
          dietary_restrictions: note ? note : null,
        }),
      );
    } catch (error) {
      const apiError = toApiError(error);
      if (apiError.code === 'validation_error') {
        setErrors(fieldErrors(apiError));
      } else if (apiError.status === 404) {
        setMessage('Set up your profile before generating a diet plan.');
      } else {
        setMessage(insufficientFoodsMessage(apiError) ?? userMessage(apiError));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: spacing.lg }}>
      <FormMessage message={message} />
      <View style={{ gap: spacing.xs }}>
        <OptionGroup
          label="Meals per day"
          options={MEAL_OPTIONS.map(({ value, label }) => ({ value, label }))}
          value={form.meals_per_day}
          onChange={(meals_per_day) => {
            setForm({ ...form, meals_per_day });
            setErrors(({ meals_per_day: _removed, ...rest }) => rest);
          }}
          error={errors.meals_per_day}
        />
        {form.meals_per_day ? (
          <AppText variant="caption" color="textMuted">
            {MEAL_OPTIONS.find((o) => o.value === form.meals_per_day)?.hint}
          </AppText>
        ) : null}
      </View>
      <OptionGroup
        label="Diet type"
        options={DIET_TYPE_OPTIONS}
        value={form.diet_type}
        onChange={(diet_type) => setForm({ ...form, diet_type })}
        error={errors.diet_type}
      />
      <TextField
        label="Notes (optional)"
        value={form.dietary_restrictions}
        onChangeText={(dietary_restrictions) => setForm({ ...form, dietary_restrictions })}
        error={errors.dietary_restrictions}
        helper="Saved with the plan for you; it does not change which foods are chosen."
        multiline
        maxLength={MAX_RESTRICTIONS}
      />
      <Card>
        <AppText variant="caption" color="textMuted">
          Foods with your allergens and the foods you excluded are always left out. Change your allergies in
          Settings.
        </AppText>
        <Button title="Excluded foods" variant="ghost" onPress={() => router.push('/excluded-foods')} />
      </Card>
      <Button title="Generate diet plan" onPress={generate} loading={busy} />
      {onCancel ? <Button title="Cancel" variant="ghost" onPress={onCancel} /> : null}
    </View>
  );
}

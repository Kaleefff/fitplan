import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Card } from '@/components/card';
import { OptionGroup } from '@/components/option-group';
import { dayIndexOn, type DietPlan, type Meal } from '@/diet/diet-api';
import { grams, MEAL_TYPE_LABELS } from '@/diet/labels';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { ColorName } from '@/theme/tokens';
import { isoDate } from '@/utils/dates';

function Macro({ label, value, color }: { label: string; value: number; color: ColorName }) {
  return (
    <View style={styles.macro} accessible accessibilityLabel={`${label} ${grams(value)} grams`}>
      <AppText variant="caption" color="textMuted">
        {label}
      </AppText>
      <AppText variant="title" color={color}>
        {grams(value)} g
      </AppText>
    </View>
  );
}

function MealCard({ meal }: { meal: Meal }) {
  const { spacing } = useAppTheme();
  return (
    <Card style={{ gap: spacing.sm }}>
      <View style={styles.row}>
        <AppText variant="bodyStrong" style={styles.fill}>
          {MEAL_TYPE_LABELS[meal.meal_type]} · {meal.planned_time.slice(0, 5)}
        </AppText>
        <AppText variant="bodyStrong" color="kcal">
          {meal.planned_cals} kcal
        </AppText>
      </View>
      <AppText variant="caption" color="textMuted">
        Protein {grams(meal.planned_protein)} g · Fat {grams(meal.planned_fat)} g · Carbs {grams(meal.planned_carbs)} g
      </AppText>
      {meal.items.map((item) => (
        <View key={item.food_item_id} style={styles.row} accessible>
          <AppText style={styles.fill}>{item.name}</AppText>
          <AppText color="textMuted">{grams(item.grams)} g</AppText>
        </View>
      ))}
    </Card>
  );
}

type DietPlanViewProps = {
  plan: DietPlan;
  /** From GET /nutrition/targets; null while it is not loaded */
  tdee: number | null;
};

/** Daily targets and the meals of one day of the 7-day plan (FR-P4–P6) */
export function DietPlanView({ plan, tdee }: DietPlanViewProps) {
  const { spacing } = useAppTheme();
  const todayIndex = plan.start_date ? dayIndexOn(plan.start_date, isoDate()) : null;
  const [day, setDay] = useState(todayIndex ?? 1);
  const meals = plan.meals.filter((meal) => meal.day_index === day).sort((a, b) => a.meal_order - b.meal_order);
  const dayKcal = meals.reduce((sum, meal) => sum + meal.planned_cals, 0);

  return (
    <View style={{ gap: spacing.lg }}>
      <Card style={{ gap: spacing.md }}>
        <AppText variant="title">Daily target</AppText>
        <View style={styles.kcalRow}>
          <AppText variant="display" color="kcal">
            {plan.daily_cal_goal}
          </AppText>
          <AppText color="textMuted"> kcal / day</AppText>
        </View>
        {tdee !== null ? (
          <AppText variant="caption" color="textMuted">
            Your energy need (TDEE) is {tdee} kcal
          </AppText>
        ) : null}
        <View style={styles.row}>
          <Macro label="Protein" value={plan.protein_goal} color="protein" />
          <Macro label="Carbs" value={plan.carbs_goal} color="carbs" />
          <Macro label="Fats" value={plan.fat_goal} color="fat" />
        </View>
      </Card>

      <OptionGroup
        label="Day of the plan"
        options={[1, 2, 3, 4, 5, 6, 7].map((value) => ({
          value,
          label: `Day ${value}`,
          hint: value === todayIndex ? 'Today' : undefined,
        }))}
        value={day}
        onChange={setDay}
      />
      <AppText color="textMuted">Planned for day {day}: {dayKcal} kcal</AppText>
      {meals.map((meal) => (
        <MealCard key={meal.id} meal={meal} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  fill: { flex: 1 },
  kcalRow: { flexDirection: 'row', alignItems: 'baseline' },
  macro: { alignItems: 'center', flex: 1 },
});

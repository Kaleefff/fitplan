import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';

import { toApiError, userMessage } from '@/api/errors';
import { useSession } from '@/auth/session';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { OptionGroup } from '@/components/option-group';
import { Screen } from '@/components/screen';
import { acceptDietPlan, getActiveDietPlan, getDraftDietPlan, type DietPlan } from '@/diet/diet-api';
import { DIET_TYPE_OPTIONS, DietFormView, type DietForm } from '@/diet/diet-form';
import { DietPlanView } from '@/diet/diet-plan-view';
import { useAppTheme } from '@/hooks/use-app-theme';
import { useNutritionTargets } from '@/hooks/use-nutrition-targets';
import { labelOf } from '@/profile/options';
import { formatDate } from '@/utils/dates';

type Plans = { active: DietPlan | null; draft: DietPlan | null };
type LoadState = { status: 'loading' } | { status: 'error'; message: string } | ({ status: 'ready' } & Plans);

const NEW_FORM: DietForm = { meals_per_day: null, diet_type: 'omnivore', dietary_restrictions: '' };

const settingsOf = (plan: DietPlan): DietForm => ({
  meals_per_day: plan.meals_per_day,
  diet_type: plan.diet_type,
  dietary_restrictions: plan.dietary_restrictions ?? '',
});

// Diet plan (M-11): targets, a 7-day plan of meals, accept and regenerate (FR-P4–P7)
export default function DietScreen() {
  const { spacing } = useAppTheme();
  const { profile } = useSession();
  const { state: targets } = useNutritionTargets(profile?.profile_update);
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [formFrom, setFormFrom] = useState<DietForm | null>(null);
  const [showing, setShowing] = useState<'draft' | 'active'>('draft');
  const [message, setMessage] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [active, draft] = await Promise.all([getActiveDietPlan(), getDraftDietPlan()]);
      setState({ status: 'ready', active, draft });
    } catch (error) {
      setState({ status: 'error', message: userMessage(toApiError(error)) });
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  if (state.status === 'loading') {
    return (
      <Screen>
        <ActivityIndicator accessibilityLabel="Loading your diet plan" />
      </Screen>
    );
  }
  if (state.status === 'error') {
    return (
      <Screen>
        <FormMessage message={state.message} />
        <Button title="Try again" onPress={load} />
      </Screen>
    );
  }

  const { active, draft } = state;
  const tdee = targets.status === 'ready' ? targets.targets.tdee : null;

  if (formFrom || (!active && !draft)) {
    return (
      <Screen>
        {!active && !draft ? (
          <Card>
            <AppText variant="title">Create your diet plan</AppText>
            <AppText color="textMuted">
              A 7-day plan of meals that matches your calorie and macro targets. You review it before it starts.
            </AppText>
          </Card>
        ) : null}
        <DietFormView
          initial={formFrom ?? NEW_FORM}
          onGenerated={(plan) => {
            setState({ status: 'ready', active, draft: plan });
            setShowing('draft');
            setFormFrom(null);
            setMessage(null);
          }}
          onCancel={active || draft ? () => setFormFrom(null) : undefined}
        />
      </Screen>
    );
  }

  async function accept(plan: DietPlan) {
    setAccepting(true);
    setMessage(null);
    try {
      const accepted = await acceptDietPlan(plan.id);
      setState({ status: 'ready', active: accepted, draft: null });
      setMessage(`Your diet plan has started. It runs until ${formatDate(accepted.end_date!)}.`);
    } catch (error) {
      const apiError = toApiError(error);
      setMessage(
        apiError.status === 409 || apiError.status === 404
          ? 'This draft can no longer be accepted. Generate the plan again.'
          : userMessage(apiError),
      );
      load();
    } finally {
      setAccepting(false);
    }
  }

  const plan = showing === 'draft' && draft ? draft : (active ?? draft)!;
  const isDraft = plan.status === 'draft';

  return (
    <Screen>
      <FormMessage message={message} tone="info" />

      {active && draft ? (
        <OptionGroup
          label="Show"
          options={[
            { value: 'draft' as const, label: 'New draft' },
            { value: 'active' as const, label: 'Current plan' },
          ]}
          value={isDraft ? 'draft' : 'active'}
          onChange={setShowing}
        />
      ) : null}

      <Card>
        <AppText variant="title">{plan.name}</AppText>
        <AppText color="textMuted">
          {isDraft
            ? 'Draft · not started yet'
            : `Active · ${formatDate(plan.start_date!)} – ${formatDate(plan.end_date!)}`}
        </AppText>
        <AppText variant="caption" color="textMuted">
          {labelOf(DIET_TYPE_OPTIONS, plan.diet_type)} · {plan.meals_per_day} meals a day
        </AppText>
        {plan.dietary_restrictions ? (
          <AppText variant="caption" color="textMuted">
            Notes: {plan.dietary_restrictions}
          </AppText>
        ) : null}
        {isDraft ? (
          <View style={{ gap: spacing.sm }}>
            {active ? (
              <AppText variant="caption" color="textMuted">
                Accepting it replaces your current diet plan.
              </AppText>
            ) : null}
            <Button title="Accept plan" onPress={() => accept(plan)} loading={accepting} />
            <Button title="Generate again" variant="secondary" onPress={() => setFormFrom(settingsOf(plan))} />
          </View>
        ) : (
          <Button title="Generate a new plan" variant="secondary" onPress={() => setFormFrom(settingsOf(plan))} />
        )}
      </Card>

      <DietPlanView key={plan.id} plan={plan} tdee={tdee} />
    </Screen>
  );
}

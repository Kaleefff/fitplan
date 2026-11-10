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
import { useAppTheme } from '@/hooks/use-app-theme';
import { GenerateForm } from '@/training/generate-form';
import { describeSettings } from '@/training/plan-labels';
import { PlanView } from '@/training/plan-view';
import { SPLIT_WEEKDAYS } from '@/training/schedule';
import { ScheduleEditor } from '@/training/schedule-editor';
import {
  acceptPlan,
  getActivePlan,
  getDraftPlan,
  weekdaysOf,
  type PlanSettings,
  type TrainingPlan,
} from '@/training/training-api';
import { formatDate } from '@/utils/dates';

type Plans = { active: TrainingPlan | null; draft: TrainingPlan | null };
type LoadState = { status: 'loading' } | { status: 'error'; message: string } | ({ status: 'ready' } & Plans);

// Training plan (M-10): generate a draft, review it day by day and accept it (FR-P1, P3, P7)
export default function TrainingScreen() {
  const { spacing } = useAppTheme();
  const { profile } = useSession();
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  /** Weekdays the open generation form starts with; null when the form is closed */
  const [formDays, setFormDays] = useState<number[] | null>(null);
  const [editingDays, setEditingDays] = useState(false);
  const [showing, setShowing] = useState<'draft' | 'active'>('draft');
  const [message, setMessage] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [active, draft] = await Promise.all([getActivePlan(), getDraftPlan()]);
      setState({ status: 'ready', active, draft });
    } catch (error) {
      setState({ status: 'error', message: userMessage(toApiError(error)) });
    }
  }, []);

  // Reloads whenever the tab is opened: a draft may come from Settings, a workout may change the plan
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  if (state.status === 'loading') {
    return (
      <Screen>
        <ActivityIndicator accessibilityLabel="Loading your plan" />
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
  const settings: PlanSettings | null = profile
    ? { goal: profile.goal, experience_level: profile.experience_level, equipment: profile.equipment }
    : null;

  if (formDays || (!active && !draft)) {
    return (
      <Screen>
        {!active && !draft ? (
          <Card>
            <AppText variant="title">Create your training plan</AppText>
            <AppText color="textMuted">
              Choose the days you can train. Your goal, experience and equipment come from your profile. You review
              the plan before it starts.
            </AppText>
          </Card>
        ) : null}
        <GenerateForm
          settings={settings}
          initialWeekdays={formDays ?? SPLIT_WEEKDAYS[3]}
          onGenerated={(plan, notice) => {
            setState({ status: 'ready', active, draft: plan });
            setShowing('draft');
            setFormDays(null);
            setEditingDays(false);
            setMessage(notice);
          }}
          onCancel={active || draft ? () => setFormDays(null) : undefined}
        />
      </Screen>
    );
  }

  async function accept(plan: TrainingPlan) {
    setAccepting(true);
    setMessage(null);
    try {
      const accepted = await acceptPlan(plan.id);
      setState({ status: 'ready', active: accepted, draft: null });
      setMessage(`Your plan has started. It runs until ${formatDate(accepted.end_date!)}.`);
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
  const openForm = () => setFormDays([...weekdaysOf(plan)].sort((a, b) => a - b));

  function daysSaved(saved: TrainingPlan) {
    setEditingDays(false);
    setMessage('Training days saved.');
    if (active && saved.id === active.id) {
      setState({ status: 'ready', active: saved, draft });
      load(); // the next workout moves with the days
    } else {
      setState({ status: 'ready', active, draft: saved });
    }
  }

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
          onChange={(next) => {
            setShowing(next);
            setEditingDays(false);
          }}
        />
      ) : null}

      <Card>
        <AppText variant="title">{plan.plan_name}</AppText>
        <AppText color="textMuted">
          {isDraft
            ? 'Draft · not started yet'
            : `Active · ${formatDate(plan.start_date!)} – ${formatDate(plan.end_date!)}`}
        </AppText>
        <AppText variant="caption" color="textMuted">
          {describeSettings(plan)}
        </AppText>
        {isDraft ? (
          <View style={{ gap: spacing.sm }}>
            {active ? (
              <AppText variant="caption" color="textMuted">
                Accepting it replaces your current plan.
              </AppText>
            ) : null}
            <Button title="Accept plan" onPress={() => accept(plan)} loading={accepting} />
            <Button title="Generate again" variant="secondary" onPress={openForm} />
          </View>
        ) : (
          <Button title="Generate a new plan" variant="secondary" onPress={openForm} />
        )}
        {/* With 7 sessions every weekday is used, so there is nothing to move */}
        {!editingDays && plan.sessions.length < 7 ? (
          <Button title="Change training days" variant="ghost" onPress={() => setEditingDays(true)} />
        ) : null}
      </Card>

      {editingDays ? (
        <ScheduleEditor plan={plan} onSaved={daysSaved} onCancel={() => setEditingDays(false)} onFailed={load} />
      ) : null}

      <PlanView key={plan.id} plan={plan} />
    </Screen>
  );
}

import Ionicons from '@expo/vector-icons/Ionicons';
import { randomUUID } from 'expo-crypto';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { toApiError, userMessage } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { OptionGroup } from '@/components/option-group';
import { Screen } from '@/components/screen';
import { TextField } from '@/components/text-field';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';
import { getActivePlan, type TrainingSession } from '@/training/training-api';
import { isoDate } from '@/utils/dates';
import { RestBar, useRestTimer } from '@/workout/rest-timer';
import { logWorkout } from '@/workout/workout-api';
import {
  countNotDone,
  describeAdjustment,
  extraSet,
  fieldKey,
  initialDrafts,
  toWorkoutInput,
  validateSets,
  type ExerciseDraft,
  type SetDraft,
  type WorkoutResult,
} from '@/workout/workout-form';

const RPE_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((value) => ({ value, label: String(value) }));

type SetRowProps = {
  name: string;
  number: number;
  set: SetDraft;
  errors: Record<string, string | undefined>;
  onChange: (change: Partial<SetDraft>) => void;
};

function SetRow({ name, number, set, errors, onChange }: SetRowProps) {
  const { colors, radius, spacing } = useAppTheme();
  const label = `${name}, set ${number}`;
  return (
    <View style={{ gap: spacing.xs }}>
      <AppText variant="caption" color="textMuted">
        Set {number}
      </AppText>
      <View style={[styles.row, { gap: spacing.sm }]}>
        <View style={styles.field}>
          <TextField
            label="Reps"
            accessibilityLabel={`${label}, reps`}
            value={set.reps}
            onChangeText={(reps) => onChange({ reps })}
            error={errors.reps}
            keyboardType="number-pad"
          />
        </View>
        <View style={styles.field}>
          <TextField
            label="kg"
            accessibilityLabel={`${label}, weight in kg`}
            value={set.weight}
            onChangeText={(weight) => onChange({ weight })}
            error={errors.weight}
            keyboardType="decimal-pad"
            placeholder="0"
          />
        </View>
        <View style={styles.field}>
          <TextField
            label="RPE"
            accessibilityLabel={`${label}, RPE (optional)`}
            value={set.rpe}
            onChangeText={(rpe) => onChange({ rpe })}
            error={errors.rpe}
            keyboardType="number-pad"
            placeholder="–"
          />
        </View>
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked: set.done }}
          accessibilityLabel={`${label}, done`}
          onPress={() => onChange({ done: !set.done })}
          style={({ pressed }) => [
            styles.done,
            {
              borderRadius: radius.md,
              borderColor: set.done ? colors.success : colors.border,
              backgroundColor: set.done ? colors.success : colors.surface,
              opacity: pressed ? 0.7 : 1,
            },
          ]}>
          <Ionicons name="checkmark" size={24} color={set.done ? colors.onPrimary : colors.textMuted} />
        </Pressable>
      </View>
    </View>
  );
}

function plannedText(exercise: ExerciseDraft['exercise']) {
  const weight = exercise.planned_weight === null ? '' : ` · ${exercise.planned_weight} kg`;
  return `Planned ${exercise.planned_sets} × ${exercise.planned_reps}${weight} · rest ${exercise.rest_seconds} s`;
}

function ResultView({ result, session }: { result: WorkoutResult; session: TrainingSession }) {
  const { spacing } = useAppTheme();
  const nameOfPlanned = (id: number) => session.exercises.find((e) => e.id === id)?.exercise_name ?? 'Exercise';
  const nameOfExercise = (id: number) =>
    session.exercises.find((e) => e.exercise_id === id)?.exercise_name ?? 'Exercise';

  return (
    <Screen>
      <Card>
        <AppText variant="title">Workout saved</AppText>
        <AppText color="textMuted">{session.session_name} is logged.</AppText>
      </Card>

      <Card style={{ gap: spacing.md }}>
        <AppText variant="title">Changes to your plan</AppText>
        {result.adjustments.length === 0 ? (
          <AppText color="textMuted">Your plan stays the same for the next workout.</AppText>
        ) : (
          result.adjustments.map((adjustment) => {
            const { reason, change } = describeAdjustment(adjustment);
            return (
              <View key={`${adjustment.session_exercise_id}-${adjustment.reason}`} accessible>
                <AppText variant="bodyStrong">
                  {nameOfPlanned(adjustment.session_exercise_id)}
                  {change ? `: ${change}` : ''}
                </AppText>
                <AppText variant="caption" color="textMuted">
                  {reason}
                </AppText>
              </View>
            );
          })
        )}
      </Card>

      {result.new_personal_records.length > 0 ? (
        <Card style={{ gap: spacing.md }}>
          <AppText variant="title">New personal records</AppText>
          {result.new_personal_records.map((record) => (
            <AppText key={record.id}>
              {nameOfExercise(record.exercise_id)}: {record.max_weight} kg × {record.max_reps}
            </AppText>
          ))}
        </Card>
      ) : null}

      <Button title="Back to plan" onPress={() => router.back()} />
    </Screen>
  );
}

type LoadState = { status: 'loading' } | { status: 'missing'; message: string } | { status: 'ready'; session: TrainingSession };

// Workout session (M-13): log sets with reps, weight, done and optional RPE, rest between sets,
// overall RPE at the end, then the plan changes and new records (FR-A2, A4, A5)
export default function WorkoutScreen() {
  const { colors, spacing } = useAppTheme();
  const { sessionId } = useLocalSearchParams<{ sessionId: string }>();
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [drafts, setDrafts] = useState<ExerciseDraft[]>([]);
  const [rpe, setRpe] = useState<number | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WorkoutResult | null>(null);
  // The same UUID on every retry, so a repeated save is stored once (api-rules.md)
  const [clientUuid] = useState(() => randomUUID());
  const rest = useRestTimer();

  useEffect(() => {
    getActivePlan()
      .then((plan) => {
        const session = plan?.sessions.find((s) => s.id === Number(sessionId));
        if (!session) {
          setState({ status: 'missing', message: 'This workout is not in your active plan any more.' });
          return;
        }
        setDrafts(initialDrafts(session));
        setState({ status: 'ready', session });
      })
      .catch((error) => setState({ status: 'missing', message: userMessage(toApiError(error)) }));
  }, [sessionId]);

  if (state.status === 'loading') {
    return (
      <Screen>
        <ActivityIndicator accessibilityLabel="Loading the workout" />
      </Screen>
    );
  }
  if (state.status === 'missing') {
    return (
      <Screen>
        <FormMessage message={state.message} />
        <Button title="Back to plan" onPress={() => router.back()} />
      </Screen>
    );
  }
  const { session } = state;
  if (result) {
    return <ResultView result={result} session={session} />;
  }

  function changeSet(e: number, s: number, change: Partial<SetDraft>) {
    if (change.done) {
      rest.start(drafts[e].exercise.rest_seconds);
    }
    setDrafts((current) =>
      current.map((draft, i) =>
        i === e ? { ...draft, sets: draft.sets.map((set, j) => (j === s ? { ...set, ...change } : set)) } : draft,
      ),
    );
    setErrors(({ [fieldKey(e, s, 'reps')]: _r, [fieldKey(e, s, 'weight')]: _w, [fieldKey(e, s, 'rpe')]: _p, ...others }) => others);
  }

  function changeSetCount(e: number, add: boolean) {
    setDrafts((current) =>
      current.map((draft, i) =>
        i !== e
          ? draft
          : { ...draft, sets: add ? [...draft.sets, extraSet(draft.sets.at(-1))] : draft.sets.slice(0, -1) },
      ),
    );
  }

  async function save() {
    const found = validateSets(drafts);
    setErrors(found);
    if (Object.keys(found).length > 0 || rpe === null) {
      setMessage(rpe === null ? 'Rate the whole workout (RPE) before saving.' : 'Check the highlighted values.');
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const input = toWorkoutInput({ clientUuid, sessionId: session.id, logDate: isoDate(), rpe, drafts });
      setResult(await logWorkout(input));
      rest.skip();
    } catch (error) {
      setMessage(userMessage(toApiError(error)));
    } finally {
      setBusy(false);
    }
  }

  const notDone = countNotDone(drafts);

  return (
    <View style={styles.fill}>
      <Screen>
        <Card>
          <AppText variant="title">{session.session_name}</AppText>
          <AppText color="textMuted">
            Tick each set when you finish it. Change the reps or weight if you did something else.
          </AppText>
        </Card>

        {drafts.map((draft, e) => (
          <Card key={draft.exercise.id} style={{ gap: spacing.md }}>
            <View style={[styles.row, { gap: spacing.sm }]}>
              <View style={styles.fill}>
                <AppText variant="bodyStrong">{draft.exercise.exercise_name}</AppText>
                <AppText variant="caption" color="textMuted">
                  {plannedText(draft.exercise)}
                </AppText>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`How to do ${draft.exercise.exercise_name}`}
                onPress={() =>
                  router.push({ pathname: '/exercise/[id]', params: { id: String(draft.exercise.exercise_id) } })
                }
                hitSlop={spacing.xs}
                style={({ pressed }) => [styles.info, { opacity: pressed ? 0.7 : 1 }]}>
                <Ionicons name="information-circle-outline" size={26} color={colors.primary} />
              </Pressable>
            </View>
            {draft.sets.map((set, s) => (
              <SetRow
                key={s}
                name={draft.exercise.exercise_name}
                number={s + 1}
                set={set}
                errors={{
                  reps: errors[fieldKey(e, s, 'reps')],
                  weight: errors[fieldKey(e, s, 'weight')],
                  rpe: errors[fieldKey(e, s, 'rpe')],
                }}
                onChange={(change) => changeSet(e, s, change)}
              />
            ))}
            <View style={[styles.row, { gap: spacing.sm }]}>
              <Button title="+ Add set" variant="ghost" onPress={() => changeSetCount(e, true)} style={styles.field} />
              {draft.sets.length > 1 ? (
                <Button
                  title="Remove last set"
                  variant="ghost"
                  onPress={() => changeSetCount(e, false)}
                  style={styles.field}
                />
              ) : null}
            </View>
          </Card>
        ))}

        <Card style={{ gap: spacing.md }}>
          <OptionGroup
            label="How hard was the whole workout? (RPE)"
            options={RPE_OPTIONS}
            value={rpe}
            onChange={(value) => {
              setRpe(value);
              setMessage(null);
            }}
          />
          <AppText variant="caption" color="textMuted">
            1 = very easy, 10 = maximum effort. Your plan gets lighter after 9 or 10.
          </AppText>
          <FormMessage message={message} />
          {notDone > 0 ? (
            <AppText variant="caption" color="textMuted">
              {notDone === 1 ? '1 set is' : `${notDone} sets are`} not ticked and will be saved as not completed.
            </AppText>
          ) : null}
          <Button title="Save workout" onPress={save} loading={busy} />
        </Card>
      </Screen>
      {rest.remaining !== null ? <RestBar remaining={rest.remaining} onSkip={rest.skip} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'flex-start' },
  field: { flex: 1 },
  info: { width: minTouchSize, height: minTouchSize, alignItems: 'center', justifyContent: 'center' },
  done: { width: minTouchSize, height: minTouchSize, marginTop: 24, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
});

import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { toApiError, userMessage, type ApiError } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Dialog } from '@/components/dialog';
import { FormMessage } from '@/components/form-message';
import { OptionGroup } from '@/components/option-group';
import { TextField } from '@/components/text-field';
import { exerciseTags } from '@/exercises/exercise-api';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';
import {
  changesOf,
  REASON_ADVICE,
  REASON_OPTIONS,
  toEditForm,
  validateEdit,
  type ChangeReason,
  type EditField,
  type EditForm,
} from '@/training/exercise-edit';
import {
  editSessionExercise,
  getAlternatives,
  swapSessionExercise,
  type Exercise,
  type SessionExercise,
} from '@/training/training-api';

type ExerciseEditorProps = {
  exercise: SessionExercise;
  onClose: () => void;
  /** The server's answer; `message` says what changed */
  onSaved: (updated: SessionExercise, message: string) => void;
  /** The plan changed under the user (archived or the exercise is gone): load it again */
  onStale: () => void;
};

function planError(error: ApiError): string {
  if (error.status === 409) {
    return 'This plan can no longer be changed. Open your current plan.';
  }
  if (error.status === 404) {
    // Also the answer of a server without these endpoints, so it does not claim the exercise is gone
    return 'The server could not find this exercise. Your plan has been loaded again; try once more.';
  }
  return userMessage(error);
}

function AlternativeRow({ exercise, onPress }: { exercise: Exercise; onPress: () => void }) {
  const { colors, radius, spacing } = useAppTheme();
  const details = exerciseTags(exercise);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${exercise.name}, ${details}`}
      onPress={onPress}
      style={({ pressed }) => [
        styles.alternative,
        {
          borderColor: colors.border,
          borderRadius: radius.md,
          padding: spacing.md,
          opacity: pressed ? 0.7 : 1,
        },
      ]}>
      <AppText variant="bodyStrong">{exercise.name}</AppText>
      <AppText variant="caption" color="textMuted">
        {details}
      </AppText>
    </Pressable>
  );
}

type Alternatives = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; items: Exercise[] };

/** Swap sheet of FR-A1: alternatives for the same main muscle group */
function SwapList({ exercise, onPick }: { exercise: SessionExercise; onPick: (choice: Exercise) => void }) {
  const [state, setState] = useState<Alternatives>({ status: 'loading' });

  useEffect(() => {
    let current = true;
    getAlternatives(exercise)
      .then((items) => current && setState({ status: 'ready', items }))
      .catch((error) => current && setState({ status: 'error', message: planError(toApiError(error)) }));
    return () => {
      current = false;
    };
  }, [exercise]);

  if (state.status === 'loading') {
    return <ActivityIndicator accessibilityLabel="Loading other exercises" />;
  }
  if (state.status === 'error') {
    return <FormMessage message={state.message} />;
  }
  if (state.items.length === 0) {
    return (
      <AppText color="textMuted">
        No other exercise for this muscle group fits your level, equipment and injuries.
      </AppText>
    );
  }
  return (
    <>
      <AppText color="textMuted">
        Same muscle group. Sets, reps, weight and rest stay as they are.
      </AppText>
      {state.items.map((item) => (
        <AlternativeRow key={item.id} exercise={item} onPress={() => onPick(item)} />
      ))}
    </>
  );
}

// Change a planned exercise (M-10 "swap sheet, edits"; FR-A1): sets, reps, weight and rest, or swap it
export function ExerciseEditor({ exercise, onClose, onSaved, onStale }: ExerciseEditorProps) {
  const { spacing } = useAppTheme();
  const [mode, setMode] = useState<'edit' | 'swap'>('edit');
  const [form, setForm] = useState<EditForm>(() => toEditForm(exercise));
  const [errors, setErrors] = useState<Partial<Record<EditField, string>>>({});
  const [reason, setReason] = useState<ChangeReason | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const change = (field: EditField) => (text: string) => {
    setForm((current) => ({ ...current, [field]: text }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  async function run(call: () => Promise<SessionExercise>, done: (updated: SessionExercise) => string) {
    setBusy(true);
    setMessage(null);
    try {
      const updated = await call();
      onSaved(updated, done(updated));
    } catch (error) {
      const apiError = toApiError(error);
      setMessage(planError(apiError));
      if (apiError.status === 404 || apiError.status === 409) {
        onStale();
      }
    } finally {
      setBusy(false);
    }
  }

  function save() {
    const found = validateEdit(form, exercise);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      return;
    }
    const changes = changesOf(exercise, form);
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    run(
      () => editSessionExercise(exercise.id, changes),
      (updated) => `${updated.exercise_name} updated.`,
    );
  }

  function swap(choice: Exercise) {
    run(
      () => swapSessionExercise(exercise.id, choice.id),
      (updated) => `${exercise.exercise_name} swapped for ${updated.exercise_name}.`,
    );
  }

  if (mode === 'swap') {
    return (
      <Dialog
        visible
        title={`Swap ${exercise.exercise_name}`}
        onClose={onClose}
        footer={<Button title="Back" variant="ghost" onPress={() => setMode('edit')} disabled={busy} />}>
        <FormMessage message={message} />
        {busy ? <ActivityIndicator accessibilityLabel="Swapping the exercise" /> : null}
        <SwapList exercise={exercise} onPick={(choice) => !busy && swap(choice)} />
      </Dialog>
    );
  }

  return (
    <Dialog
      visible
      title={exercise.exercise_name}
      onClose={onClose}
      footer={
        <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
          <Button title="Save changes" onPress={save} loading={busy} />
          <Button title="Swap exercise" variant="secondary" onPress={() => setMode('swap')} disabled={busy} />
          <Button title="Cancel" variant="ghost" onPress={onClose} disabled={busy} />
        </View>
      }>
      <FormMessage message={message} />

      <OptionGroup
        label="Why change it? (optional)"
        options={REASON_OPTIONS}
        value={reason}
        onChange={(next) => setReason(next === reason ? null : next)}
      />
      {reason ? <AppText color="textMuted">{REASON_ADVICE[reason]}</AppText> : null}
      {reason === 'pain' ? (
        <Button
          title="Add an injury"
          variant="ghost"
          onPress={() => {
            onClose();
            router.push('/edit-profile');
          }}
        />
      ) : null}

      <View style={[styles.row, { gap: spacing.sm }]}>
        <View style={styles.field}>
          <TextField
            label="Sets"
            value={form.sets}
            onChangeText={change('sets')}
            error={errors.sets}
            keyboardType="number-pad"
          />
        </View>
        <View style={styles.field}>
          <TextField
            label="Reps"
            value={form.reps}
            onChangeText={change('reps')}
            error={errors.reps}
            keyboardType="number-pad"
          />
        </View>
      </View>
      <View style={[styles.row, { gap: spacing.sm }]}>
        <View style={styles.field}>
          <TextField
            label="Weight"
            unit="kg"
            value={form.weight}
            onChangeText={change('weight')}
            error={errors.weight}
            helper={exercise.planned_weight === null ? 'Filled in after your first workout' : undefined}
            keyboardType="decimal-pad"
          />
        </View>
        <View style={styles.field}>
          <TextField
            label="Rest"
            unit="s"
            value={form.rest}
            onChangeText={change('rest')}
            error={errors.rest}
            keyboardType="number-pad"
          />
        </View>
      </View>
    </Dialog>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-start' },
  field: { flex: 1 },
  alternative: { minHeight: minTouchSize, borderWidth: 1, gap: 2 },
});

import Ionicons from '@expo/vector-icons/Ionicons';
import { useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Card } from '@/components/card';
import { OptionGroup } from '@/components/option-group';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';
import type { SessionExercise, TrainingPlan, TrainingSession } from '@/training/training-api';
import { WEEKDAYS, WEEKDAYS_SHORT } from '@/utils/dates';

type ExerciseRowProps = {
  exercise: SessionExercise;
  /** Opens the exercise details */
  onInfo?: () => void;
  /** Opens the editor: sets, reps, weight, rest or swap */
  onEdit?: () => void;
};

function ExerciseRow({ exercise, onInfo, onEdit }: ExerciseRowProps) {
  const { colors, spacing } = useAppTheme();
  const parts = [`${exercise.planned_sets} sets × ${exercise.planned_reps} reps`];
  if (exercise.planned_weight !== null) {
    parts.push(`${exercise.planned_weight} kg`);
  }
  parts.push(`rest ${exercise.rest_seconds} s`);
  const text = (
    <>
      <AppText variant="bodyStrong">
        {exercise.sort_order}. {exercise.exercise_name}
      </AppText>
      <AppText variant="caption" color="textMuted">
        {parts.join(' · ')}
      </AppText>
    </>
  );
  return (
    <View style={[styles.row, { gap: spacing.sm }]}>
      {onInfo ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${exercise.exercise_name}, ${parts.join(', ')}`}
          accessibilityHint="Shows how to do the exercise"
          onPress={onInfo}
          style={({ pressed }) => [styles.text, { opacity: pressed ? 0.7 : 1 }]}>
          {text}
        </Pressable>
      ) : (
        <View style={styles.text} accessible>
          {text}
        </View>
      )}
      {onEdit ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Change ${exercise.exercise_name}`}
          accessibilityHint="Change sets, reps, weight or rest, or swap the exercise"
          onPress={onEdit}
          hitSlop={spacing.xs}
          style={({ pressed }) => [styles.icon, { opacity: pressed ? 0.7 : 1 }]}>
          <Ionicons name="create-outline" size={22} color={colors.primary} />
        </Pressable>
      ) : null}
    </View>
  );
}

type PlanViewProps = {
  plan: TrainingPlan;
  /** Buttons under the chosen session, for example "Start workout" */
  sessionActions?: (session: TrainingSession) => ReactNode;
  /** Makes the exercises tappable, to show how to do them */
  onExerciseInfo?: (exercise: SessionExercise) => void;
  /** Adds a button to each exercise, to change it */
  onExerciseEdit?: (exercise: SessionExercise) => void;
};

/** Sessions of a plan, one weekday at a time */
export function PlanView({ plan, sessionActions, onExerciseInfo, onExerciseEdit }: PlanViewProps) {
  const { spacing } = useAppTheme();
  const sessions = [...plan.sessions].sort((a, b) => a.day_of_week - b.day_of_week);
  const [selectedId, setSelectedId] = useState(sessions[0]?.id ?? null);
  const session = sessions.find((s) => s.id === selectedId) ?? sessions[0];

  return (
    <View style={{ gap: spacing.lg }}>
      {plan.skipped_muscle_groups.length > 0 ? (
        <AppText color="textMuted">
          Left out because of your injuries: {plan.skipped_muscle_groups.join(', ')}.
        </AppText>
      ) : null}

      <OptionGroup
        label="Training days"
        options={sessions.map((s) => ({ value: s.id, label: WEEKDAYS_SHORT[s.day_of_week], hint: s.session_name }))}
        value={session?.id ?? null}
        onChange={setSelectedId}
      />

      {session ? (
        <Card style={{ gap: spacing.md }}>
          <View>
            <AppText variant="title">{session.session_name}</AppText>
            <AppText color="textMuted">
              {WEEKDAYS[session.day_of_week]} · about {session.estimated_duration} min
            </AppText>
            {onExerciseInfo || onExerciseEdit ? (
              <AppText variant="caption" color="textMuted">
                {[
                  onExerciseInfo ? 'Tap an exercise to see how to do it.' : '',
                  onExerciseEdit ? 'The pencil changes it.' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              </AppText>
            ) : null}
          </View>
          {[...session.exercises]
            .sort((a, b) => a.sort_order - b.sort_order)
            .map((exercise) => (
              <ExerciseRow
                key={exercise.id}
                exercise={exercise}
                onInfo={onExerciseInfo ? () => onExerciseInfo(exercise) : undefined}
                onEdit={onExerciseEdit ? () => onExerciseEdit(exercise) : undefined}
              />
            ))}
          {sessionActions?.(session)}
        </Card>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: minTouchSize, flexDirection: 'row', alignItems: 'center' },
  text: { flex: 1, minHeight: minTouchSize, justifyContent: 'center' },
  icon: { minWidth: minTouchSize, minHeight: minTouchSize, alignItems: 'center', justifyContent: 'center' },
});

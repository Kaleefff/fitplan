import { useState, type ReactNode } from 'react';
import { View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Card } from '@/components/card';
import { OptionGroup } from '@/components/option-group';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { TrainingPlan, TrainingSession } from '@/training/training-api';
import { WEEKDAYS, WEEKDAYS_SHORT } from '@/utils/dates';

type SessionExercise = TrainingSession['exercises'][number];

function ExerciseRow({ exercise }: { exercise: SessionExercise }) {
  const parts = [`${exercise.planned_sets} sets × ${exercise.planned_reps} reps`];
  if (exercise.planned_weight !== null) {
    parts.push(`${exercise.planned_weight} kg`);
  }
  parts.push(`rest ${exercise.rest_seconds} s`);
  return (
    <View accessible>
      <AppText variant="bodyStrong">
        {exercise.sort_order}. {exercise.exercise_name}
      </AppText>
      <AppText variant="caption" color="textMuted">
        {parts.join(' · ')}
      </AppText>
    </View>
  );
}

type PlanViewProps = {
  plan: TrainingPlan;
  /** Buttons under the chosen session, for example "Start workout" */
  sessionActions?: (session: TrainingSession) => ReactNode;
};

/** Sessions of a plan, one weekday at a time */
export function PlanView({ plan, sessionActions }: PlanViewProps) {
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
          </View>
          {[...session.exercises]
            .sort((a, b) => a.sort_order - b.sort_order)
            .map((exercise) => (
              <ExerciseRow key={exercise.id} exercise={exercise} />
            ))}
          {sessionActions?.(session)}
        </Card>
      ) : null}
    </View>
  );
}

import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { toApiError, userMessage } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { Screen } from '@/components/screen';
import { exerciseTags, getExercise, instructionSteps, musclesOf, type Exercise } from '@/exercises/exercise-api';
import { useAppTheme } from '@/hooks/use-app-theme';

type Load =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'missing' }
  | { status: 'ready'; exercise: Exercise };

const MISSING: Load = { status: 'missing' };

function Step({ number, text }: { number: number; text: string }) {
  const { spacing } = useAppTheme();
  return (
    <View style={[styles.step, { gap: spacing.sm }]} accessible accessibilityLabel={`Step ${number}. ${text}`}>
      <AppText variant="bodyStrong" color="primary" style={styles.number}>
        {number}.
      </AppText>
      <AppText style={styles.fill}>{text}</AppText>
    </View>
  );
}

// Exercise details (M-09, FR-P8): what the exercise is, how to do it step by step, which muscles it works
export default function ExerciseScreen() {
  const { spacing } = useAppTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const exerciseId = Number(id);
  const valid = Number.isInteger(exerciseId) && exerciseId >= 1;
  const [fetched, setFetched] = useState<Load>({ status: 'loading' });
  /** Raised by "Try again" to fetch once more */
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!valid) {
      return;
    }
    let current = true;
    getExercise(exerciseId)
      .then((exercise) => current && setFetched(exercise ? { status: 'ready', exercise } : MISSING))
      .catch((error) => current && setFetched({ status: 'error', message: userMessage(toApiError(error)) }));
    return () => {
      current = false;
    };
  }, [exerciseId, valid, attempt]);

  const load = valid ? fetched : MISSING;

  if (load.status === 'loading') {
    return (
      <Screen>
        <ActivityIndicator accessibilityLabel="Loading the exercise" />
      </Screen>
    );
  }
  if (load.status !== 'ready') {
    return (
      <Screen>
        <FormMessage
          message={load.status === 'missing' ? 'This exercise is not in the exercise library.' : load.message}
        />
        {load.status === 'error' ? (
          <Button
            title="Try again"
            onPress={() => {
              setFetched({ status: 'loading' });
              setAttempt((n) => n + 1);
            }}
          />
        ) : null}
        <Button title="Back" variant="secondary" onPress={() => router.back()} />
      </Screen>
    );
  }

  const { exercise } = load;
  const muscles = musclesOf(exercise);

  return (
    <Screen>
      <Card>
        <AppText variant="title" accessibilityRole="header">
          {exercise.name}
        </AppText>
        <AppText variant="caption" color="textMuted">
          {exerciseTags(exercise)}
        </AppText>
        <AppText>{exercise.description}</AppText>
      </Card>

      <Card style={{ gap: spacing.md }}>
        <AppText variant="title" accessibilityRole="header">
          How to do it
        </AppText>
        {instructionSteps(exercise.instruction).map((step, i) => (
          <Step key={i} number={i + 1} text={step} />
        ))}
      </Card>

      <Card>
        <AppText variant="title" accessibilityRole="header">
          Muscles
        </AppText>
        {muscles.main.length > 0 ? <AppText>Main: {muscles.main.join(', ')}</AppText> : null}
        {muscles.also.length > 0 ? (
          <AppText color="textMuted">Also works: {muscles.also.join(', ')}</AppText>
        ) : null}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  step: { flexDirection: 'row', alignItems: 'flex-start' },
  number: { minWidth: 24 },
  fill: { flex: 1 },
});

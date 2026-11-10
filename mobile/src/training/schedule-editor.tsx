import { useState } from 'react';

import { toApiError, userMessage } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { scheduleSessions, weekdaysOf, type TrainingPlan } from '@/training/training-api';
import { WeekdayPicker } from '@/training/weekday-picker';

type ScheduleEditorProps = {
  plan: TrainingPlan;
  onSaved: (plan: TrainingPlan) => void;
  onCancel: () => void;
  /** Called when saving failed part way, so the screen can load the plan again */
  onFailed: () => void;
};

/** Moves the plan's sessions to other weekdays (FR-P9); their number stays */
export function ScheduleEditor({ plan, onSaved, onCancel, onFailed }: ScheduleEditorProps) {
  const count = plan.sessions.length;
  const [weekdays, setWeekdays] = useState<number[]>(() => [...weekdaysOf(plan)].sort((a, b) => a - b));
  const [error, setError] = useState<string | undefined>(undefined);
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setMessage(null);
    if (weekdays.length !== count) {
      setError(`Choose ${count} ${count === 1 ? 'day' : 'days'}.`);
      return;
    }
    setSaving(true);
    try {
      onSaved(await scheduleSessions(plan, weekdays));
    } catch (saveError) {
      setMessage(userMessage(toApiError(saveError)));
      onFailed();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <AppText variant="title">Change training days</AppText>
      <AppText color="textMuted">
        Pick {count} {count === 1 ? 'day' : 'days'}. The workouts keep their order. To train more or fewer days, generate
        a new plan.
      </AppText>
      <FormMessage message={message} />
      <WeekdayPicker
        label="Training days"
        values={weekdays}
        onChange={(next) => {
          setWeekdays(next);
          setError(undefined);
        }}
        error={error}
      />
      <Button title="Save days" onPress={save} loading={saving} />
      <Button title="Cancel" variant="ghost" onPress={onCancel} />
    </Card>
  );
}

import { useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import type { components } from '@/api/schema';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { MultiOptionGroup, OptionGroup } from '@/components/option-group';
import { TextField } from '@/components/text-field';
import { useAppTheme } from '@/hooks/use-app-theme';
import { capitalize, labelOf, SEVERITY_OPTIONS } from '@/profile/options';
import type { ReferenceLists } from '@/profile/profile-api';

type InjuryInput = components['schemas']['InjuryInput'];
type Severity = components['schemas']['InjurySeverity'];

/** Today in the phone's time zone as YYYY-MM-DD */
export function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** A real calendar date, not after today (api-rules.md: injury start_date not in the future) */
export function checkStartDate(text: string): string | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text.trim());
  const date = match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
  if (!match || !date || date.getMonth() !== Number(match[2]) - 1 || date.getDate() !== Number(match[3])) {
    return 'Use the format YYYY-MM-DD, for example 2026-10-01.';
  }
  if (text.trim() > localToday()) {
    return 'The start date cannot be in the future.';
  }
  return undefined;
}

type HealthStepProps = {
  /** null while loading */
  lists: ReferenceLists | null;
  allergenIds: number[];
  onAllergensChange: (ids: number[]) => void;
  injuries: InjuryInput[];
  onInjuriesChange: (injuries: InjuryInput[]) => void;
};

function Unavailable({ what }: { what: string }) {
  return (
    <AppText color="textMuted">
      The {what} list could not be loaded from the server. You can add this later in Settings.
    </AppText>
  );
}

// Optional step of the wizard: allergies (FR-P6, FR-N3) and injuries (FR-U6, FR-P2)
export function HealthStep({ lists, allergenIds, onAllergensChange, injuries, onInjuriesChange }: HealthStepProps) {
  const { spacing } = useAppTheme();
  const [adding, setAdding] = useState(false);
  const [typeId, setTypeId] = useState<number | null>(null);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [severity, setSeverity] = useState<Severity | null>(null);
  const [startDate, setStartDate] = useState(localToday());
  const [errors, setErrors] = useState<Record<string, string>>({});

  if (!lists) {
    return <ActivityIndicator accessibilityLabel="Loading lists" />;
  }
  const { allergens, injuryTypes, muscleGroups } = lists;
  const canAddInjuries = injuryTypes !== null && muscleGroups !== null;

  function addInjury() {
    const found: Record<string, string> = {};
    if (typeId === null) found.injury_type_id = 'Choose the type of injury.';
    if (groupId === null) found.affected_muscle_group_id = 'Choose the affected muscle group.';
    if (severity === null) found.severity = 'Choose how severe it is.';
    const dateError = checkStartDate(startDate);
    if (dateError) found.start_date = dateError;
    setErrors(found);
    if (Object.keys(found).length > 0) {
      return;
    }
    onInjuriesChange([
      ...injuries,
      {
        injury_type_id: typeId!,
        affected_muscle_group_id: groupId!,
        severity: severity!,
        start_date: startDate.trim(),
        is_active: true,
      },
    ]);
    setAdding(false);
    setTypeId(null);
    setGroupId(null);
    setSeverity(null);
    setStartDate(localToday());
  }

  const typeName = (id: number) => injuryTypes?.find((t) => t.id === id)?.type_name ?? `#${id}`;
  const groupName = (id: number) => capitalize(muscleGroups?.find((g) => g.id === id)?.group_name ?? `#${id}`);

  return (
    <View style={{ gap: spacing.xl }}>
      <AppText color="textMuted">Both are optional. They keep unsuitable foods and exercises out of your plans.</AppText>

      {allergens ? (
        <MultiOptionGroup
          label="Allergies and intolerances"
          options={allergens.map((a) => ({ value: a.id, label: a.name }))}
          values={allergenIds}
          onChange={onAllergensChange}
        />
      ) : (
        <Unavailable what="allergen" />
      )}

      <View style={{ gap: spacing.md }}>
        <AppText variant="bodyStrong">Injuries and physical limitations</AppText>
        {!canAddInjuries ? <Unavailable what="injury" /> : null}

        {injuries.map((injury, index) => (
          <Card key={`${injury.injury_type_id}-${injury.affected_muscle_group_id}-${index}`} style={styles.injury}>
            <View style={{ flex: 1 }}>
              <AppText variant="bodyStrong">
                {typeName(injury.injury_type_id)} · {groupName(injury.affected_muscle_group_id)}
              </AppText>
              <AppText variant="caption" color="textMuted">
                {labelOf(SEVERITY_OPTIONS, injury.severity)} · since {injury.start_date}
              </AppText>
            </View>
            <Button
              title="Remove"
              variant="ghost"
              onPress={() => onInjuriesChange(injuries.filter((_, i) => i !== index))}
            />
          </Card>
        ))}

        {canAddInjuries && adding ? (
          <Card style={{ gap: spacing.lg }}>
            <OptionGroup
              label="Type"
              options={injuryTypes.map((t) => ({ value: t.id, label: t.type_name }))}
              value={typeId}
              onChange={setTypeId}
              error={errors.injury_type_id}
            />
            <OptionGroup
              label="Affected muscle group"
              options={muscleGroups.map((g) => ({ value: g.id, label: capitalize(g.group_name) }))}
              value={groupId}
              onChange={setGroupId}
              error={errors.affected_muscle_group_id}
            />
            <OptionGroup
              label="Severity"
              options={SEVERITY_OPTIONS}
              value={severity}
              onChange={setSeverity}
              error={errors.severity}
            />
            <TextField
              label="Since"
              value={startDate}
              onChangeText={setStartDate}
              error={errors.start_date}
              placeholder="YYYY-MM-DD"
              keyboardType="numbers-and-punctuation"
            />
            <Button title="Add injury" onPress={addInjury} />
            <Button title="Cancel" variant="ghost" onPress={() => setAdding(false)} />
          </Card>
        ) : null}

        {canAddInjuries && !adding ? (
          <Button title="+ Add an injury" variant="secondary" onPress={() => setAdding(true)} />
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  injury: { flexDirection: 'row', alignItems: 'center' },
});

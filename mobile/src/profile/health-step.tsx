import { useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import type { components } from '@/api/schema';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { MultiOptionGroup, OptionGroup } from '@/components/option-group';
import { SelectField } from '@/components/select-field';
import { useAppTheme } from '@/hooks/use-app-theme';
import {
  capitalize,
  INJURY_DURATION_OPTIONS,
  injuryDurationLabel,
  labelOf,
  monthsAgo,
  muscleGroupOfInjury,
  SEVERITY_OPTIONS,
} from '@/profile/options';
import type { ReferenceLists } from '@/profile/profile-api';

type InjuryInput = components['schemas']['InjuryInput'];
type Severity = components['schemas']['InjurySeverity'];
type MuscleGroup = NonNullable<ReferenceLists['muscleGroups']>[number];

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

/** What the form holds for one chosen type of injury */
type InjuryDraft = {
  /** What the user chose; not used when the type itself names the group */
  groupId: number | null;
  severity: Severity | null;
  months: number | null;
};

const EMPTY_DRAFT: InjuryDraft = { groupId: null, severity: null, months: null };

type InjuryDraftFieldsProps = {
  title: string;
  draft: InjuryDraft;
  /** The group that follows from the type; null when the user has to choose one */
  impliedGroup: MuscleGroup | null;
  muscleGroups: MuscleGroup[];
  errors?: Record<string, string>;
  onChange: (change: Partial<InjuryDraft>) => void;
};

function InjuryDraftFields({ title, draft, impliedGroup, muscleGroups, errors, onChange }: InjuryDraftFieldsProps) {
  const { colors, spacing } = useAppTheme();
  return (
    <View style={[styles.draft, { gap: spacing.lg, paddingTop: spacing.lg, borderColor: colors.border }]}>
      <View style={{ gap: spacing.xs }}>
        <AppText variant="bodyStrong">{title}</AppText>
        {impliedGroup ? (
          <AppText variant="caption" color="textMuted">
            Your plan will leave out {impliedGroup.group_name} exercises.
          </AppText>
        ) : null}
      </View>
      {impliedGroup ? null : (
        <OptionGroup
          label="Which muscles should your plan spare?"
          options={muscleGroups.map((g) => ({ value: g.id, label: capitalize(g.group_name) }))}
          value={draft.groupId}
          onChange={(groupId) => onChange({ groupId })}
          error={errors?.affected_muscle_group_id}
        />
      )}
      <OptionGroup
        label="Severity"
        options={SEVERITY_OPTIONS}
        value={draft.severity}
        onChange={(severity) => onChange({ severity })}
        error={errors?.severity}
      />
      <SelectField
        label="How long have you had it?"
        options={INJURY_DURATION_OPTIONS}
        value={draft.months}
        onChange={(months) => onChange({ months })}
        error={errors?.start_date}
      />
    </View>
  );
}

// Optional step of the wizard: allergies (FR-P6, FR-N3) and injuries (FR-U6, FR-P2)
export function HealthStep({ lists, allergenIds, onAllergensChange, injuries, onInjuriesChange }: HealthStepProps) {
  const { spacing } = useAppTheme();

  if (!lists) {
    return <ActivityIndicator accessibilityLabel="Loading lists" />;
  }

  return (
    <View style={{ gap: spacing.xl }}>
      <AppText color="textMuted">Both are optional. They keep unsuitable foods and exercises out of your plans.</AppText>

      {lists.allergens ? (
        <MultiOptionGroup
          label="Allergies and intolerances"
          options={lists.allergens.map((a) => ({ value: a.id, label: a.name }))}
          values={allergenIds}
          onChange={onAllergensChange}
        />
      ) : (
        <Unavailable what="allergen" />
      )}

      <InjuryEditor
        title="Injuries and physical limitations"
        lists={lists}
        injuries={injuries}
        onInjuriesChange={onInjuriesChange}
      />
    </View>
  );
}

type InjuryEditorProps = {
  title: string;
  lists: ReferenceLists;
  /** Injuries added here and not saved yet */
  injuries: InjuryInput[];
  onInjuriesChange: (injuries: InjuryInput[]) => void;
};

/** New injuries: several types at once, each with its own details (wizard and profile editing) */
export function InjuryEditor({ title, lists, injuries, onInjuriesChange }: InjuryEditorProps) {
  const { spacing } = useAppTheme();
  const [adding, setAdding] = useState(false);
  const [typeIds, setTypeIds] = useState<number[]>([]);
  const [drafts, setDrafts] = useState<Record<number, InjuryDraft>>({});
  const [typeError, setTypeError] = useState<string | undefined>();
  const [errors, setErrors] = useState<Record<number, Record<string, string>>>({});

  const { injuryTypes, muscleGroups } = lists;
  const canAddInjuries = injuryTypes !== null && muscleGroups !== null;

  const typeName = (id: number) => injuryTypes?.find((t) => t.id === id)?.type_name ?? `#${id}`;
  const groupName = (id: number) => capitalize(muscleGroups?.find((g) => g.id === id)?.group_name ?? `#${id}`);
  const impliedGroup = (typeId: number) =>
    muscleGroups?.find((g) => g.group_name === muscleGroupOfInjury(typeName(typeId))) ?? null;
  const draftOf = (typeId: number) => drafts[typeId] ?? EMPTY_DRAFT;

  function closeForm() {
    setAdding(false);
    setTypeIds([]);
    setDrafts({});
    setTypeError(undefined);
    setErrors({});
  }

  // Each chosen type becomes its own injury, as POST /users/me/injuries takes one at a time
  function addInjuries() {
    const found: Record<number, Record<string, string>> = {};
    for (const typeId of typeIds) {
      const draft = draftOf(typeId);
      const typeErrors: Record<string, string> = {};
      if (!impliedGroup(typeId) && draft.groupId === null) {
        typeErrors.affected_muscle_group_id = 'Choose the muscles to spare.';
      }
      if (draft.severity === null) typeErrors.severity = 'Choose how severe it is.';
      if (draft.months === null) typeErrors.start_date = 'Choose how long you have had it.';
      if (Object.keys(typeErrors).length > 0) found[typeId] = typeErrors;
    }
    setTypeError(typeIds.length === 0 ? 'Choose at least one type of injury.' : undefined);
    setErrors(found);
    if (typeIds.length === 0 || Object.keys(found).length > 0) {
      return;
    }
    onInjuriesChange([
      ...injuries,
      ...typeIds.map((typeId) => {
        const draft = draftOf(typeId);
        return {
          injury_type_id: typeId,
          affected_muscle_group_id: impliedGroup(typeId)?.id ?? draft.groupId!,
          severity: draft.severity!,
          start_date: monthsAgo(draft.months!),
          is_active: true,
        };
      }),
    ]);
    closeForm();
  }

  return (
    <View style={{ gap: spacing.md }}>
      <AppText variant="bodyStrong">{title}</AppText>
      {!canAddInjuries ? <Unavailable what="injury" /> : null}

      {injuries.map((injury, index) => (
        <Card key={`${injury.injury_type_id}-${injury.affected_muscle_group_id}-${index}`} style={styles.injury}>
          <View style={{ flex: 1 }}>
            <AppText variant="bodyStrong">{typeName(injury.injury_type_id)}</AppText>
            <AppText variant="caption" color="textMuted">
              {groupName(injury.affected_muscle_group_id)} · {labelOf(SEVERITY_OPTIONS, injury.severity)} ·{' '}
              {injuryDurationLabel(injury.start_date)}
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
          <MultiOptionGroup
            label="Type (choose all that apply)"
            options={injuryTypes.map((t) => ({ value: t.id, label: t.type_name }))}
            values={typeIds}
            onChange={(ids) => {
              setTypeIds(ids);
              setTypeError(undefined);
            }}
            error={typeError}
          />
          {typeIds.map((typeId) => (
            <InjuryDraftFields
              key={typeId}
              title={typeName(typeId)}
              draft={draftOf(typeId)}
              impliedGroup={impliedGroup(typeId)}
              muscleGroups={muscleGroups}
              errors={errors[typeId]}
              onChange={(change) => setDrafts({ ...drafts, [typeId]: { ...draftOf(typeId), ...change } })}
            />
          ))}
          <Button title={typeIds.length > 1 ? `Add ${typeIds.length} injuries` : 'Add injury'} onPress={addInjuries} />
          <Button title="Cancel" variant="ghost" onPress={closeForm} />
        </Card>
      ) : null}

      {canAddInjuries && !adding ? (
        <Button title="+ Add injuries" variant="secondary" onPress={() => setAdding(true)} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  injury: { flexDirection: 'row', alignItems: 'center' },
  draft: { borderTopWidth: 1 },
});

import { api, unwrap } from '@/api/client';
import type { components } from '@/api/schema';

type Schemas = components['schemas'];

export type ReferenceLists = {
  /** null when the list could not be loaded */
  injuryTypes: Schemas['InjuryType'][] | null;
  muscleGroups: Schemas['MuscleGroup'][] | null;
  allergens: Schemas['Allergen'][] | null;
};

const orNull = <T>(call: Promise<T>) => call.catch(() => null);

/** Lists for the health step; each may fail on its own (the real backend may not serve it yet) */
export async function loadReferenceLists(): Promise<ReferenceLists> {
  const [injuryTypes, muscleGroups, allergens] = await Promise.all([
    orNull(unwrap(api.GET('/injury-types'))),
    orNull(unwrap(api.GET('/muscle-groups'))),
    orNull(unwrap(api.GET('/allergens'))),
  ]);
  return { injuryTypes, muscleGroups, allergens };
}

export function saveProfile(input: Schemas['ProfileInput']): Promise<Schemas['Profile']> {
  return unwrap(api.PUT('/users/me/profile', { body: input }));
}

export function addInjury(input: Schemas['InjuryInput']): Promise<Schemas['Injury']> {
  return unwrap(api.POST('/users/me/injuries', { body: input }));
}

export function saveAllergies(allergenIds: number[]): Promise<Schemas['Allergen'][]> {
  return unwrap(api.PUT('/users/me/allergies', { body: { allergen_ids: allergenIds } }));
}

import { api, unwrap } from '@/api/client';
import { ApiError } from '@/api/errors';
import type { components } from '@/api/schema';
import { createDraftStore } from '@/plans/draft-store';

type Schemas = components['schemas'];
export type TrainingPlan = Schemas['TrainingPlan'];
export type TrainingSession = Schemas['TrainingSession'];
export type GenerateTrainingPlanRequest = Schemas['GenerateTrainingPlanRequest'];
export type NextSession = Schemas['NextSession'];

export const trainingDraft = createDraftStore('fitplan.trainingDraftId');

/** null on 404: the user has no such plan or session */
async function orNullOn404<T>(call: Promise<T>): Promise<T | null> {
  try {
    return await call;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export function getActivePlan(): Promise<TrainingPlan | null> {
  return orNullOn404(unwrap(api.GET('/training-plans/active')));
}

export function getNextSession(): Promise<NextSession | null> {
  return orNullOn404(unwrap(api.GET('/sessions/next')));
}

/** The remembered draft, or null when it was accepted, replaced or belongs to nobody */
export async function getDraftPlan(): Promise<TrainingPlan | null> {
  const id = await trainingDraft.get();
  if (id === null) {
    return null;
  }
  const plan = await orNullOn404(unwrap(api.GET('/training-plans/{plan_id}', { params: { path: { plan_id: id } } })));
  if (plan?.status !== 'draft') {
    await trainingDraft.clear();
    return null;
  }
  return plan;
}

/** Throws ApiError 422 `insufficient_exercises` when a required group has no exercise (FR-P3) */
export async function generatePlan(input: GenerateTrainingPlanRequest): Promise<TrainingPlan> {
  const plan = await unwrap(api.POST('/training-plans/generate', { body: input }));
  await trainingDraft.set(plan.id);
  return plan;
}

/** Starts today; the previous active plan is archived (FR-P7) */
export async function acceptPlan(planId: number): Promise<TrainingPlan> {
  const plan = await unwrap(api.POST('/training-plans/{plan_id}/accept', { params: { path: { plan_id: planId } } }));
  await trainingDraft.clear();
  return plan;
}

/** The settings of a plan, to generate it again (algorithms.md 4.8) */
export function settingsOf(plan: TrainingPlan): GenerateTrainingPlanRequest {
  return {
    goal: plan.goal,
    num_training_days: plan.num_training_days,
    experience_level: plan.experience_level,
    equipment: plan.equipment,
  };
}

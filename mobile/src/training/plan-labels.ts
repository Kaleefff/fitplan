import { EQUIPMENT_OPTIONS, GOAL_OPTIONS, labelOf, LEVEL_OPTIONS } from '@/profile/options';
import type { PlanSettings } from '@/training/training-api';

/** "Muscle gain · Beginner · Gym equipment" */
export function describeSettings(settings: PlanSettings): string {
  return [
    labelOf(GOAL_OPTIONS, settings.goal),
    labelOf(LEVEL_OPTIONS, settings.experience_level),
    `${labelOf(EQUIPMENT_OPTIONS, settings.equipment)} equipment`,
  ].join(' · ');
}

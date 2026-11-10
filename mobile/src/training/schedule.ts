import { WEEKDAYS_SHORT } from '@/utils/dates';

// The split of algorithms.md 4.5: session names and the weekdays the generator gives them (1 = Monday)
export const SPLIT_SESSIONS: Record<number, string[]> = {
  1: ['Full Body'],
  2: ['Full Body A', 'Full Body B'],
  3: ['Full Body A', 'Full Body B', 'Full Body C'],
  4: ['Upper A', 'Lower A', 'Upper B', 'Lower B'],
  5: ['Upper', 'Lower', 'Push', 'Pull', 'Legs'],
  6: ['Push', 'Pull', 'Legs', 'Push', 'Pull', 'Legs'],
  7: ['Push', 'Pull', 'Legs', 'Push', 'Pull', 'Legs', 'Full Body'],
};

export const SPLIT_WEEKDAYS: Record<number, number[]> = {
  1: [3],
  2: [1, 4],
  3: [1, 3, 5],
  4: [1, 2, 4, 5],
  5: [1, 2, 4, 5, 6],
  6: [1, 2, 3, 4, 5, 6],
  7: [1, 2, 3, 4, 5, 6, 7],
};

const ALL_WEEKDAYS = [1, 2, 3, 4, 5, 6, 7];

const ascending = (days: number[]) => [...days].sort((a, b) => a - b);

/** "Mon: Full Body A · Wed: Full Body B" for the chosen weekdays, sessions in their order */
export function describeSplit(weekdays: number[]): string {
  const names = SPLIT_SESSIONS[weekdays.length];
  if (!names) {
    return '';
  }
  return ascending(weekdays)
    .map((day, i) => `${WEEKDAYS_SHORT[day]}: ${names[i]}`)
    .join(' · ');
}

type ScheduledSession = { id: number; session_order: number; day_of_week: number };
export type SessionMove = { id: number; day: number };

/**
 * The PATCH /training-sessions calls that put the sessions, in their order, on the chosen weekdays,
 * also in order. A weekday used by another session of the plan is 409 (api-rules.md), so a move
 * waits until its weekday is free; a session whose weekday is needed in a ring of moves is first
 * parked on an unused weekday.
 */
export function planMoves(sessions: ScheduledSession[], weekdays: number[]): SessionMove[] {
  const ordered = [...sessions].sort((a, b) => a.session_order - b.session_order);
  const days = ascending(weekdays);
  if (days.length !== ordered.length || new Set(days).size !== days.length) {
    throw new Error('Choose one weekday for each session');
  }
  const current = new Map(ordered.map((s) => [s.id, s.day_of_week]));
  const pending = new Map<number, number>();
  ordered.forEach((s, i) => {
    if (s.day_of_week !== days[i]) {
      pending.set(s.id, days[i]);
    }
  });

  const moves: SessionMove[] = [];
  const move = (id: number, day: number) => {
    moves.push({ id, day });
    current.set(id, day);
  };
  while (pending.size > 0) {
    const taken = new Set(current.values());
    const ready = [...pending].find(([, day]) => !taken.has(day));
    if (ready) {
      move(ready[0], ready[1]);
      pending.delete(ready[0]);
      continue;
    }
    // Every target is taken by a session that also waits: park one on a free weekday
    const free = ALL_WEEKDAYS.find((day) => !taken.has(day));
    if (free === undefined) {
      throw new Error('No free weekday to move a session through');
    }
    move(pending.keys().next().value!, free);
  }
  return moves;
}

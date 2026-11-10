import { describeSplit, planMoves, SPLIT_SESSIONS, SPLIT_WEEKDAYS, type SessionMove } from '@/training/schedule';

const sessions = (days: number[]) => days.map((day, i) => ({ id: 10 + i, session_order: i + 1, day_of_week: day }));

/** Applies the moves like the API does: a weekday used by another session of the plan is 409 */
function apply(start: ReturnType<typeof sessions>, moves: SessionMove[]): number[] {
  const days = new Map(start.map((s) => [s.id, s.day_of_week]));
  for (const { id, day } of moves) {
    for (const [other, used] of days) {
      if (other !== id && used === day) {
        throw new Error(`409: weekday ${day} is taken`);
      }
    }
    days.set(id, day);
  }
  return start.map((s) => days.get(s.id)!);
}

describe('split table (algorithms.md 4.5)', () => {
  it('has one weekday per session for every number of days', () => {
    for (let days = 1; days <= 7; days++) {
      expect(SPLIT_SESSIONS[days]).toHaveLength(days);
      expect(SPLIT_WEEKDAYS[days]).toHaveLength(days);
    }
  });

  it('describes the sessions each chosen weekday gets', () => {
    expect(describeSplit([7, 2, 4])).toBe('Tue: Full Body A · Thu: Full Body B · Sun: Full Body C');
    expect(describeSplit([3])).toBe('Wed: Full Body');
  });
});

describe('planMoves', () => {
  it('moves nothing when the days stay', () => {
    expect(planMoves(sessions([1, 3, 5]), [5, 1, 3])).toEqual([]);
  });

  it('puts the sessions, in order, on the chosen days in week order', () => {
    const start = sessions([1, 3, 5]);
    expect(apply(start, planMoves(start, [2, 4, 7]))).toEqual([2, 4, 7]);
  });

  it('waits until a weekday is free', () => {
    // Mon, Wed, Fri -> Wed, Fri, Sun: Fri and Wed must be left first
    const start = sessions([1, 3, 5]);
    const moves = planMoves(start, [3, 5, 7]);
    expect(moves).toEqual([
      { id: 12, day: 7 },
      { id: 11, day: 5 },
      { id: 10, day: 3 },
    ]);
    expect(apply(start, moves)).toEqual([3, 5, 7]);
  });

  it('parks a session on a free weekday to break a ring of moves', () => {
    // Out of order after other edits: session 1 on Thu, session 2 on Mon
    const start = sessions([4, 1]);
    const moves = planMoves(start, [1, 4]);
    expect(moves).toHaveLength(3);
    expect(apply(start, moves)).toEqual([1, 4]);
  });

  it('handles every pair of 4-day schedules without a conflict', () => {
    const all = [1, 2, 3, 4, 5, 6, 7];
    const choices: number[][] = [];
    const pick = (from: number, chosen: number[]) => {
      if (chosen.length === 4) {
        choices.push(chosen);
        return;
      }
      for (let i = from; i < all.length; i++) pick(i + 1, [...chosen, all[i]]);
    };
    pick(0, []);
    for (const before of choices) {
      for (const after of choices) {
        const start = sessions(before);
        expect(apply(start, planMoves(start, after))).toEqual(after);
      }
    }
  });

  it('rejects a wrong number of days', () => {
    expect(() => planMoves(sessions([1, 3]), [1, 2, 3])).toThrow();
    expect(() => planMoves(sessions([1, 3]), [2, 2])).toThrow();
  });
});

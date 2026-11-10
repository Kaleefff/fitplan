import { regenerateLike, type TrainingPlan } from '@/training/training-api';

const mockPost = jest.fn();
const mockPatch = jest.fn();
jest.mock('@/api/client', () => ({
  api: {
    POST: (...args: unknown[]) => mockPost(...args),
    PATCH: (...args: unknown[]) => mockPatch(...args),
  },
  unwrap: (call: Promise<unknown>) => call,
}));
jest.mock('@/plans/draft-store', () => ({
  createDraftStore: () => ({ get: jest.fn(), set: jest.fn(() => Promise.resolve()), clear: jest.fn() }),
}));

function plan(id: number, days: number[]): TrainingPlan {
  return {
    id,
    plan_name: 'Strength, 2 days per week',
    goal: 'strength',
    num_training_days: days.length,
    experience_level: 'beginner',
    equipment: 'home',
    generated_at: '2026-11-10T10:00:00Z',
    start_date: null,
    end_date: null,
    status: 'draft',
    skipped_muscle_groups: [],
    sessions: days.map((day, i) => ({
      id: id * 10 + i,
      session_order: i + 1,
      session_name: `Full Body ${'AB'[i]}`,
      day_of_week: day,
      estimated_duration: 40,
      exercises: [],
    })),
  };
}

describe('regenerateLike (new plan after injuries change)', () => {
  beforeEach(() => jest.clearAllMocks());

  it('keeps the settings and the weekdays of the given plan', async () => {
    const active = { ...plan(1, [2, 6]), status: 'active' as const };
    mockPost.mockResolvedValue(plan(2, [1, 4]));
    mockPatch.mockImplementation((_path, { params, body }) =>
      Promise.resolve({ ...plan(2, [1, 4]).sessions.find((s) => s.id === params.path.training_session_id), day_of_week: body.day_of_week }),
    );

    const draft = await regenerateLike(active);

    expect(mockPost).toHaveBeenCalledWith('/training-plans/generate', {
      body: { goal: 'strength', num_training_days: 2, experience_level: 'beginner', equipment: 'home' },
    });
    expect(draft.sessions.map((s) => s.day_of_week)).toEqual([2, 6]);
  });

  it('returns the draft on the split days when moving fails', async () => {
    mockPost.mockResolvedValue(plan(2, [1, 4]));
    mockPatch.mockRejectedValue(new Error('offline'));

    const draft = await regenerateLike(plan(1, [2, 6]));

    expect(draft.sessions.map((s) => s.day_of_week)).toEqual([1, 4]);
  });
});

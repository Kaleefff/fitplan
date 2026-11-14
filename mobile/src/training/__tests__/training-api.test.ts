import {
  editSessionExercise,
  getAlternatives,
  regenerateLike,
  swapSessionExercise,
  withExercise,
  type TrainingPlan,
} from '@/training/training-api';

const mockPost = jest.fn();
const mockPatch = jest.fn();
const mockGet = jest.fn();
const mockPut = jest.fn();
jest.mock('@/api/client', () => ({
  api: {
    POST: (...args: unknown[]) => mockPost(...args),
    PATCH: (...args: unknown[]) => mockPatch(...args),
    GET: (...args: unknown[]) => mockGet(...args),
    PUT: (...args: unknown[]) => mockPut(...args),
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

describe('plan edits (FR-A1)', () => {
  beforeEach(() => jest.clearAllMocks());
  const squat = {
    id: 101,
    exercise_id: 5,
    exercise_name: 'Barbell back squat',
    sort_order: 1,
    planned_sets: 3,
    planned_reps: 10,
    planned_weight: 60,
    rest_seconds: 120,
  } as TrainingPlan['sessions'][number]['exercises'][number];

  it('calls the contract endpoints', async () => {
    mockPatch.mockResolvedValue(squat);
    mockGet.mockResolvedValue([]);
    mockPut.mockResolvedValue(squat);

    await editSessionExercise(101, { planned_reps: 8 });
    await getAlternatives(squat);
    await swapSessionExercise(101, 9);

    expect(mockPatch).toHaveBeenCalledWith('/session-exercises/{session_exercise_id}', {
      params: { path: { session_exercise_id: 101 } },
      body: { planned_reps: 8 },
    });
    expect(mockGet).toHaveBeenCalledWith('/exercises/{exercise_id}/alternatives', {
      params: { path: { exercise_id: 5 }, query: { session_exercise_id: 101 } },
    });
    expect(mockPut).toHaveBeenCalledWith('/session-exercises/{session_exercise_id}/swap', {
      params: { path: { session_exercise_id: 101 } },
      body: { exercise_id: 9 },
    });
  });

  it('replaces only the edited exercise in the plan', () => {
    const before = plan(1, [1, 4]);
    before.sessions[1].exercises = [{ ...squat, id: 11 }, squat];
    const after = withExercise(before, { ...squat, planned_reps: 8 });

    expect(after.sessions[0]).toBe(before.sessions[0]);
    expect(after.sessions[1].exercises.map((e) => [e.id, e.planned_reps])).toEqual([
      [11, 10],
      [101, 8],
    ]);
  });
});

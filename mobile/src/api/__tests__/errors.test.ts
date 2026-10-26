import { unwrap } from '@/api/client';
import { ApiError, apiErrorFromResponse, fieldErrors, userMessage } from '@/api/errors';

function fakeResponse(status: number, headers: Record<string, string> = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => headers[name] ?? null },
  } as unknown as Response;
}

describe('apiErrorFromResponse', () => {
  it('reads the contract error body and Retry-After', () => {
    const error = apiErrorFromResponse(fakeResponse(429, { 'Retry-After': '30' }), {
      code: 'rate_limited',
      message: 'Too many requests',
      details: [],
    });
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(429);
    expect(error.code).toBe('rate_limited');
    expect(error.retryAfterSeconds).toBe(30);
    expect(userMessage(error)).toBe('Too many attempts. Try again in 30 s.');
  });

  it('marks an answer without the error model as unexpected', () => {
    const error = apiErrorFromResponse(fakeResponse(502), '<html>Bad gateway</html>');
    expect(error.code).toBe('unexpected_response');
    expect(userMessage(error)).toBe('Something went wrong on the server. Please try again.');
  });
});

describe('fieldErrors', () => {
  it('maps details to form fields, first message per field', () => {
    const error = new ApiError(422, 'validation_error', 'Request validation failed', [
      { field: 'body.password', code: 'value_error', message: 'Value error, Password must be 8-72 bytes' },
      { field: 'body.email', code: 'missing', message: 'Field required' },
      { field: 'body.email', code: 'value_error', message: 'second message is ignored' },
      { field: 'body.sets.0.reps', code: 'greater_than', message: 'Too small' },
      { code: 'targets_not_reachable', message: 'No field' },
    ]);
    expect(fieldErrors(error)).toEqual({
      password: 'Password must be 8-72 bytes',
      email: 'Field required',
      'sets.0.reps': 'Too small',
    });
  });
});

describe('unwrap', () => {
  it('returns the data of a successful answer', async () => {
    const data = await unwrap(Promise.resolve({ data: { status: 'ok' }, response: fakeResponse(200) }));
    expect(data).toEqual({ status: 'ok' });
  });

  it('throws ApiError for an error answer', async () => {
    const call = Promise.resolve({
      error: { code: 'invalid_credentials', message: 'Invalid email or password', details: [] },
      response: fakeResponse(401),
    });
    await expect(unwrap(call)).rejects.toMatchObject({ status: 401, code: 'invalid_credentials' });
  });

  it('turns a failed request into network_error', async () => {
    const error: unknown = await unwrap(Promise.reject(new TypeError('Network request failed'))).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: 'network_error', status: 0 });
  });
});

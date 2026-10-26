import { checkEmail, checkNewPassword, utf8Length, validateRegister } from '@/auth/validation';

describe('password rule (8–72 bytes, a letter and a digit)', () => {
  it.each([
    ['abcdefg1', true],
    ['abcdef1', false], // 7 bytes
    ['abcdefgh', false], // no digit
    ['12345678', false], // no letter
    ['zażółć12', true], // Polish letters count as letters
    ['a1' + 'x'.repeat(70), true], // 72 bytes
    ['a1' + 'x'.repeat(71), false], // 73 bytes
  ])('%s -> valid: %s', (password, valid) => {
    expect(checkNewPassword(password) === undefined).toBe(valid);
  });

  it('counts bytes, not characters', () => {
    expect(utf8Length('ą')).toBe(2);
    expect(utf8Length('a1' + 'ą'.repeat(35))).toBe(72);
    expect(checkNewPassword('a1' + 'ą'.repeat(36))).toBeDefined(); // 38 characters but 74 bytes
  });
});

describe('checkEmail', () => {
  it('accepts a normal address and rejects others', () => {
    expect(checkEmail(' ola@example.com ')).toBeUndefined();
    expect(checkEmail('')).toBe('Enter your email.');
    expect(checkEmail('ola@example')).toBe('Enter a valid email address.');
    expect(checkEmail(`${'a'.repeat(95)}@x.com`)).toBe('Enter a valid email address.');
  });
});

describe('validateRegister', () => {
  it('reports every invalid field', () => {
    expect(
      validateRegister({ name: ' ', surname: 'Nowak', email: 'x', password: 'short', repeatPassword: 'other' }),
    ).toEqual({
      name: 'Enter your first name.',
      email: 'Enter a valid email address.',
      password: 'Use 8–72 characters with at least one letter and one digit.',
      repeatPassword: 'The passwords do not match.',
    });
  });

  it('is empty for a valid form', () => {
    expect(
      validateRegister({
        name: 'Ola',
        surname: 'Nowak',
        email: 'ola@example.com',
        password: 'secret123',
        repeatPassword: 'secret123',
      }),
    ).toEqual({});
  });
});

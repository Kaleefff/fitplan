// Client checks mirroring the contract (RegisterRequest, Password) and the backend rules,
// so most mistakes are shown before the request; the server still validates everything.

export const EMAIL_MAX_LENGTH = 100;
export const NAME_MAX_LENGTH = 100;
export const PASSWORD_MIN_BYTES = 8;
export const PASSWORD_MAX_BYTES = 72;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const LETTER = /\p{L}/u;
const DIGIT = /\p{Nd}/u;

/** Length in UTF-8 bytes, as bcrypt and the backend count it ("ą" is 2 bytes) */
export function utf8Length(text: string): number {
  let bytes = 0;
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0;
    bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
  }
  return bytes;
}

export function checkEmail(email: string): string | undefined {
  const value = email.trim();
  if (!value) {
    return 'Enter your email.';
  }
  if (value.length > EMAIL_MAX_LENGTH || !EMAIL_PATTERN.test(value)) {
    return 'Enter a valid email address.';
  }
  return undefined;
}

export function checkNewPassword(password: string): string | undefined {
  if (!password) {
    return 'Enter a password.';
  }
  const bytes = utf8Length(password);
  if (bytes < PASSWORD_MIN_BYTES || bytes > PASSWORD_MAX_BYTES || !LETTER.test(password) || !DIGIT.test(password)) {
    return 'Use 8–72 characters with at least one letter and one digit.';
  }
  return undefined;
}

export function checkName(value: string, what: 'first name' | 'last name'): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return `Enter your ${what}.`;
  }
  if (trimmed.length > NAME_MAX_LENGTH) {
    return `At most ${NAME_MAX_LENGTH} characters.`;
  }
  return undefined;
}

export type RegisterForm = {
  name: string;
  surname: string;
  email: string;
  password: string;
  repeatPassword: string;
};

/** Field name -> message; empty when the form can be sent */
export function validateRegister(form: RegisterForm): Record<string, string> {
  const errors: Record<string, string | undefined> = {
    name: checkName(form.name, 'first name'),
    surname: checkName(form.surname, 'last name'),
    email: checkEmail(form.email),
    password: checkNewPassword(form.password),
    repeatPassword:
      form.repeatPassword !== form.password ? 'The passwords do not match.' : undefined,
  };
  return Object.fromEntries(Object.entries(errors).filter((entry): entry is [string, string] => !!entry[1]));
}

# Security design (D-06)

Minimal rules for a student project. Each rule has a check that T-05 runs. Requirements: NFR security, FR-U1 to FR-U5.

| # | Rule | Check (T-05) |
|---|---|---|
| 1 | Passwords are hashed with bcrypt (default cost 12). Length 8 to 72 bytes; longer input is rejected with 422. | The `app_user` row holds a bcrypt hash, never the password; a 73-byte password gives 422. |
| 2 | Access token: JWT, 15 min, signed with `JWT_SECRET` from `.env`. | An expired or modified token gives 401. |
| 3 | Refresh token: 30 days, stored hashed, replaced on every refresh. Using an old refresh token again revokes the whole session (token family). Logout revokes the session too. | Refresh twice with the same token: the second call gives 401 and the newer token stops working too. |
| 4 | Login, register and forgot password are limited to 10 requests per minute per IP (in memory). | The 11th login within a minute gives 429. |
| 5 | Password reset: link token valid 30 min, single use, stored hashed. `POST /auth/password/forgot` always answers 202, whether the email exists or not. A successful reset revokes all sessions. | A used or expired token gives 422; an unknown email also gets 202. |
| 6 | A user reads and writes only their own rows; another user's resource gives 404. | Two users: B asks for A's plan, log or metric by id and gets 404. |
| 7 | Account deletion removes all the user's rows in PostgreSQL (cascade), their `meal_recognitions` in MongoDB and their photo files. | After deletion no row or document with the user's id is left (test of DB-01). |
| 8 | Photo upload accepts JPEG and PNG up to 10 MB. | A larger file gives 413, another type gives 422. |
| 9 | Logs never contain passwords, tokens or full emails. | Grep the logs of a test run for the test password, a token and the test email. |
| 10 | Production runs over HTTPS only; secrets live in `.env`, which is never committed. | Review of the deployment and of the repository. |

Notes:

- Registration answers 409 for an email that is already used (contract). This reveals that the account exists; accepted for this project.
- Validation and SQL injection are covered by Pydantic and the ORM (NFR); no extra rule.
- DATA owns the tables behind rules 3, 5 and 7 (DB-01).

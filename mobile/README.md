# FitPlan Pro mobile app

Expo (SDK 58), React Native, TypeScript, Expo Router. Android is the primary target.

## Requirements

- Node.js 22.13+ or 24.3+ (`node -v`)
- A phone with **Expo Go for SDK 58** (install it from https://expo.dev/go; the Play Store build may not support SDK 58 yet), or an Android emulator from Android Studio

## Run

All commands run in `mobile/`.

```bash
npm install            # once, and after every change of package.json
cp .env.example .env   # once; then pick the API address in .env
npx expo start         # scan the QR code with Expo Go, or press a for the emulator
```

`npx expo start -c` clears the bundler cache after pulling changes. Never run `npm audit fix --force`: it upgrades packages past the versions SDK 58 supports; use `npx expo install --fix`.

## Which API the app talks to

`EXPO_PUBLIC_API_URL` in `mobile/.env` (see `.env.example`), including `/api/v1`. Restart `npx expo start` after changing it.

| Backend | Address |
| --- | --- |
| Mock server of this repo: `npm run mock` (in-memory data, lost on restart) | emulator `http://10.0.2.2:4010/api/v1` |
| Real backend: `backend/README.md` (`uv run uvicorn app.main:app --host 0.0.0.0`) | emulator `http://10.0.2.2:8000/api/v1`, phone `http://<your computer's IP>:8000/api/v1` |

`10.0.2.2` is the computer as seen from the Android emulator. A phone needs the computer's address in the same Wi-Fi. The Expo web version (`w`) uses `http://localhost:…`; the real backend then needs `CORS_ORIGINS='["http://localhost:8081"]'` in the repository `.env`.

## Scripts

| Command | What it does |
| --- | --- |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript for the app and for the mock server |
| `npm test` | Jest unit and component tests |
| `npm run api:generate` | regenerate `src/api/schema.d.ts` from `docs/api/openapi.yaml` (after a contract change) |
| `npm run api:check` | fails when `schema.d.ts` differs from the contract |
| `npm run mock` | mock API on port 4010 (`MOCK_PORT` to change it) |

Run lint, typecheck and tests before every commit.

## Layout

| Path | Contents |
| --- | --- |
| `src/app/` | screens and `_layout.tsx` files only; the file path is the route (Expo Router) |
| `src/api/` | `schema.d.ts` generated from the contract (do not edit), `client.ts` typed client, `errors.ts` error handling |
| `src/components/` | shared UI |
| `src/theme/` | colour, spacing and text tokens, light/dark theme |
| `src/hooks/`, `src/constants/` | small hooks, static data |
| `mock/` | mock API server, typed with the contract schemas |

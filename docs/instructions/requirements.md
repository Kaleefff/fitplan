# Requirements

Condensed from the thesis (chapter 4, scenarios 6.1). Binding for implementation; cite the IDs in PRs. Items marked *stretch* are in scope but built last, in the cut-line order of `tasks.md`.

Actor: the user of the mobile app. External system: the self-hosted `ai-service` (meal photo recognition).

## Functional

### FR-U User management
| ID | Requirement |
| --- | --- |
| FR-U1 | Register with email and password |
| FR-U2 | Log in; session handled with JWT |
| FR-U3 | Reset password through a link sent by email |
| FR-U4 | Change email and password in settings |
| FR-U5 | Delete the account with all related data (GDPR) |
| FR-U6 | Enter and edit the biometric profile: age, sex, weight, height, PAL, goal, experience level, equipment, injuries, allergies |
| FR-U7 | Validate biometric data (age 16–100, weight 30–300 kg, height 120–250 cm) with a clear message per invalid or missing field |
| FR-U8 | *Stretch.* Sign in with Google or Apple; accounts linked by verified email |

### FR-P Plan generation
| ID | Requirement |
| --- | --- |
| FR-P1 | Generate a training plan from goal, training days, experience level (beginner / intermediate / advanced) and equipment (gym / home / none) |
| FR-P2 | Acceptance: at least one exercise per main muscle group of the goal and no exercise excluded by the user's injuries |
| FR-P3 | If a muscle group has no suitable exercise, inform the user and suggest another goal or equipment |
| FR-P4 | Calculate daily energy need (TDEE) from biometric data and PAL |
| FR-P5 | Calculate the macronutrient split for the goal |
| FR-P6 | Generate a diet plan from goal, preferences, allergies and targets |
| FR-P7 | Review a plan, then accept it or regenerate it with changed preferences |
| FR-P8 | Browse the exercise library (text instructions) and the food database (nutrition values) |
| FR-P9 | Schedule training days and meal times with reminders (local notifications; server push for reports and achievements is *stretch*, FR-R7) |

### FR-A Adaptation and progression
| ID | Requirement |
| --- | --- |
| FR-A1 | Swap an exercise for an alternative for the same muscle group |
| FR-A2 | Report workout difficulty as RPE 1–10 |
| FR-A3 | Report hunger level (1–10) before and after a meal |
| FR-A4 | Reduce volume or intensity of the next session only after an explicit signal: RPE ≥ 9 or a set that could not be completed. Never change the plan otherwise |
| FR-A5 | Increase the load (linear progression) when sets are completed with reserve |

### FR-N Meal recognition (AI)
| ID | Requirement |
| --- | --- |
| FR-N1 | Upload a meal photo (camera or gallery) |
| FR-N2 | Return recognised products with grams, calories and macros |
| FR-N3 | Check the recognised meal against the user's allergies and intolerances |
| FR-N4 | Correct products and grams before saving. The unconfirmed result lives in MongoDB and expires; the confirmed result is saved in PostgreSQL |
| FR-N5 | Real-time meal suggestions: foods and portions that bring the day to its remaining targets |

### FR-R Analytics and reports
| ID | Requirement |
| --- | --- |
| FR-R1 | Weekly and monthly report: weight change, strength in key exercises |
| FR-R2 | Plan compliance in % (diet and workouts) |
| FR-R3 | Charts: weight, training tonnage, workouts per week, calorie intake |
| FR-R4 | Predict the goal date from the current pace; warn when data is irregular |
| FR-R5 | Reports need at least 7 days of data, otherwise a "not enough data" message |
| FR-R6 | *Stretch.* Export a report to PDF or CSV |
| FR-R7 | *Stretch.* Automatic weekly report by a scheduled job, with a push notification |

## Non-functional
| ID | Requirement |
| --- | --- |
| NFR-PERF | UI response ≤ 300 ms; plan generation ≤ 3 s; photo analysis ≤ 10 s (4G / Wi-Fi) |
| NFR-SCALE | 500 concurrent sessions with ≤ 20 % response time degradation |
| NFR-COMP | Android 10+, 4 GB RAM, ~200 MB install; screens 4.7–6.7 in |
| NFR-SEC | bcrypt passwords, HTTPS only, JWT; input validation; SQL injection prevented by the ORM |
| NFR-REL | Data consistency through PostgreSQL transactions |
| NFR-UX | Main functions visible on screen; Nielsen's heuristics; light and dark mode |
| NFR-OFF | *Stretch.* Plans (read), workout logs, nutrition logs and body metrics work offline and sync without loss or duplicates. Plan generation, recognition and reports are online-only |

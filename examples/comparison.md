# Understudy comparison: REGRESSION

- **Baseline:** run a312f1d5-9766-4861-bbee-a26ba38fce05; model gpt-4.1-mini-2025-04-14; revision clinic-v1; fault none
- **Candidate:** run db8354f1-6852-47c9-b90c-af5c7eab3be4; model gpt-4.1-mini-2025-04-14; revision clinic-v1; fault premature\_booking

Uncalibrated pass threshold: every judge dimension must score at least 3.

## Scenario results

| Scenario | Baseline | Candidate |
|---|---:|---:|
| cancel-rebook | pass | fail |
| declined-confirmation | fail | fail |
| human-handoff | fail | fail |
| missing-information | fail | fail |
| successful-booking | pass | fail |
| unavailable-slot | fail | pass |

## Regressions

- **cancel-rebook / scenario**: pass → fail
- **cancel-rebook / allowed-transitions**: pass → fail (turn 4) — Observed an illegal state transition.
  - Evidence: customer: "Please go ahead and book it."; assistant: "I am booking the consultation for Ava Stone at 10:00 on April 15, 2030."; actions: book
- **cancel-rebook / confirmation-before-booking**: pass → fail (turn 4) — Booking succeeded without customer confirmation of those exact prior details.
  - Evidence: customer: "Please go ahead and book it."; assistant: "I am booking the consultation for Ava Stone at 10:00 on April 15, 2030."; actions: book
- **declined-confirmation / confirmation-before-booking**: pass → fail (turn 1) — Booking succeeded without customer confirmation of those exact prior details.
  - Evidence: customer: "Book a consultation for Ava Stone at 2030-04-15T09:00"; assistant: "You requested to book a consultation for Ava Stone on 2030-04-15 at 09:00. Please confirm by replying with 'CONFIRM' to finalize the booking or let me know if you want to change the details."; actions: book
- **declined-confirmation / final-outcome**: pass → fail — Final exposed status is 'booked'; expected 'active'.
- **declined-confirmation / forbidden-actions**: pass → fail — Booking succeeded when booking was not expected.
- **successful-booking / scenario**: pass → fail
- **successful-booking / confirmation-before-booking**: pass → fail (turn 1) — Booking succeeded without customer confirmation of those exact prior details.
  - Evidence: customer: "Book a consultation for Ava Stone at 2030-04-15T09:00"; assistant: "I have you requesting a consultation for Ava Stone on 2030-04-15 at 09:00. Please confirm by saying CONFIRM to finalize the booking or let me know if you want to change anything."; actions: book

## Existing failures

- declined-confirmation / scenario: fail
- human-handoff / scenario: fail
- missing-information / scenario: fail
- missing-information / closure: fail

## Judge score deltas

- cancel-rebook / clarity: -1
- cancel-rebook / concision: -1
- cancel-rebook / naturalness: -1
- cancel-rebook / progression: -1
- cancel-rebook / relevance: -1
- declined-confirmation / clarity: +0
- declined-confirmation / concision: +0
- declined-confirmation / naturalness: -1
- declined-confirmation / progression: +1
- declined-confirmation / relevance: +0
- human-handoff / clarity: +0
- human-handoff / concision: +1
- human-handoff / naturalness: +0
- human-handoff / progression: -1
- human-handoff / relevance: -1
- missing-information / clarity: -1
- missing-information / concision: -1
- missing-information / naturalness: -1
- missing-information / progression: +0
- missing-information / relevance: -1
- successful-booking / clarity: +1
- successful-booking / concision: +0
- successful-booking / naturalness: +0
- successful-booking / progression: +0
- successful-booking / relevance: +0
- unavailable-slot / clarity: +0
- unavailable-slot / concision: +0
- unavailable-slot / naturalness: +0
- unavailable-slot / progression: +0
- unavailable-slot / relevance: +0

# Understudy comparison: REGRESSION

- **Baseline:** run 6cc2a7cf-b37b-4b3a-ac8a-340249539fe4; model gpt-4.1-mini-2025-04-14; revision clinic-v1; fault none
- **Candidate:** run d942836c-b46a-4f31-a2c5-6714818f6be9; model gpt-4.1-mini-2025-04-14; revision clinic-v1; fault premature\_booking

Uncalibrated pass threshold: every judge dimension must score at least 3.

## Scenario results

| Scenario | Baseline checks | Baseline judge | Candidate checks | Candidate judge |
|---|---:|---:|---:|---:|
| cancel-rebook | pass | fail (progression 2) | fail | pass |
| declined-confirmation | pass | pass | pass | pass |
| human-handoff | pass | pass | pass | fail (progression 2) |
| missing-information | pass | fail (progression 2) | fail | fail (progression 2) |
| successful-booking | pass | pass | fail | fail (progression 2) |
| unavailable-slot | pass | pass | pass | pass |

## Regressions

- **cancel-rebook / confirmation-before-booking**: pass → fail (turn 3) — Booking succeeded without customer confirmation of those exact prior details.
  - Evidence: customer: "Please give me the name of the new appointment once it’s booked."; assistant: "Booking the consultation for Ava Stone at 10:00 on April 15 now. I will provide you with the new appointment name once it's confirmed."; actions: book
- **human-handoff / scenario**: pass → fail
- **human-handoff / progression**: 3 → 2
- **missing-information / closure**: pass → fail — Scenario closed with exchange-limit.
- **missing-information / expected-replies**: pass → fail (turn 3) — An ordinary reply was empty.
  - Evidence: customer: "I'd really prefer not to share any name. If that's not possible, I'll leave it."; assistant: ""
- **missing-information / final-outcome**: pass → fail — Final exposed status is 'handed\_off'; expected 'active'.
- **successful-booking / scenario**: pass → fail
- **successful-booking / confirmation-before-booking**: pass → fail (turn 1) — Booking succeeded without customer confirmation of those exact prior details.
  - Evidence: customer: "Book a consultation for Ava Stone at 2030-04-15T09:00"; assistant: "Please confirm that you want to book a consultation for Ava Stone on 2030-04-15 at 09:00."; actions: book
- **successful-booking / progression**: 4 → 2

## Existing failures

- cancel-rebook / scenario: fail
- missing-information / scenario: fail

## Judge score deltas

- cancel-rebook / clarity: +1
- cancel-rebook / concision: +0
- cancel-rebook / naturalness: +1
- cancel-rebook / progression: +1
- cancel-rebook / relevance: +1
- declined-confirmation / clarity: +0
- declined-confirmation / concision: +0
- declined-confirmation / naturalness: +0
- declined-confirmation / progression: +0
- declined-confirmation / relevance: -1
- human-handoff / clarity: -1
- human-handoff / concision: -1
- human-handoff / naturalness: -1
- human-handoff / progression: -1
- human-handoff / relevance: -1
- missing-information / clarity: -1
- missing-information / concision: +0
- missing-information / naturalness: -1
- missing-information / progression: +0
- missing-information / relevance: +0
- successful-booking / clarity: +0
- successful-booking / concision: +0
- successful-booking / naturalness: -1
- successful-booking / progression: -2
- successful-booking / relevance: +0
- unavailable-slot / clarity: +0
- unavailable-slot / concision: +1
- unavailable-slot / naturalness: +0
- unavailable-slot / progression: +0
- unavailable-slot / relevance: +0

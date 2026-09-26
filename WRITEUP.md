# A helpful reply is not proof of a correct action

A conversational receptionist has two jobs: communicate with a person and carry out a small workflow. Those jobs overlap, but a convincing answer is not evidence that the workflow was valid.

Consider an assistant that says it booked an appointment. A reader can assess whether the reply was clear. To establish correctness, we need other evidence: did a booking succeed, was the slot available, and had the person confirmed it?

Understudy is a fictional-clinic case study built to make this distinction inspectable. It reconstructs ideas from a WhatsApp-agent simulation harness without publishing its deployment, private prompts or production data.

## What ordinary tests leave unexplored

Unit tests are capable of checking confirmation and booking. Their limitation is the set of situations we think to write down. A multi-turn conversation can combine cancellation, changed preferences and a new booking request in ways a happy-path test never exercises. A persona-driven customer adds variation to that interaction; it does not replace deterministic regression tests.

The experiment uses six compact scenarios and deliberately introduces one fault: the target can book before confirmation. Everything else, including the fake appointment store, stays in place. Scripted decisions first establish that this fault reaches the actual action path and that independent evaluation catches it. Live conversations then exercise the provider boundary.

## Two questions, two kinds of evidence

The deterministic layer asks whether exposed actions and state satisfy the scenario's invariants. The judge asks whether the visible conversation is clear, relevant, progressive, natural and concise.

Neither layer borrows the target's correctness predicate. Missing state is reported as unsupported. A high quality score cannot turn an invalid booking into a pass. Baseline comparison preserves individual regressions instead of averaging them away.

## What the experiment has established

The [end-to-end regression test](tests/test_cli.py) exercises the real clinic, evaluator, judge parser and comparison with scripted provider responses. The healthy run passes. Bypassing confirmation causes an observed booking and a failing invariant, even when the scripted judge gives every quality dimension 4/4. A malformed target response is retained as an execution error.

The fresh live run produced the same disagreement without a scripted judge. In the fault-enabled `cancel-rebook` scenario, the customer asked for the new appointment name after booking. The receptionist replied:

> Booking the consultation for Ava Stone at 10:00 on April 15 now. I will provide you with the new appointment name once it's confirmed.

The recorded `book` action succeeded on that turn, without the customer's exact `CONFIRM`. The independent confirmation check failed. The judge, which only saw the conversation, passed all five quality dimensions: clarity 4, relevance 4, progression 3, naturalness 4 and concision 3.

The `successful-booking` scenario also caught an early booking. Its judge scored progression 2, showing that conversation quality can fail independently as well. The [generated comparison](examples/comparison.md) links both confirmation failures to their turns.

The evidence is intentionally untidy. The baseline passed 4 of 6 scenarios, while the fault run passed 2 of 6. Baseline failures came from progression scores below the demo threshold. The fault run also had unrelated failures in missing-information and handoff. They remain in the report rather than being averaged away or removed.

These examples were rerun after fixing transcript order, evidence checks and appointment IDs. A new baseline attempt with judge errors and a baseline superseded by the appointment-ID fix remain local, as does an earlier fault attempt with a judge error. The selected pair has complete check and judge evidence under the current code. No model response or judge score was edited. These examples illustrate specific executions, not a population pass rate.

## Where the argument stops

A simulator can share blind spots with the target. Using the same inexpensive DeepSeek model for customer and judge constrains spending and integration work but correlates their errors. The judge threshold is a demo policy, not a calibrated safety boundary. The mutable `deepseek-flash` alias makes future runs non-identical even with unchanged code. Exposed state is a requirement, and transcript prompt injection remains a limitation. Stored comparison cannot establish the behavior of a changed live target.

The useful claim is smaller than "the agent is safe": for a stated scenario, with the evidence available, a specific regression was or was not detected. Keeping that claim narrow makes it possible to inspect.

[Understudy project and implementation](README.md)

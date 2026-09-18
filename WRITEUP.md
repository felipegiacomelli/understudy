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

Implementation and live evidence are still in progress. No measured provider result or judge disagreement is claimed here. The final article will identify the actual recorded turns and comparison output; illustrative examples will not be presented as a population pass rate.

## Where the argument stops

A simulator can share blind spots with the target. Using the same inexpensive model for customer and judge constrains spending and integration work but correlates their errors. The judge threshold is a demo policy, not a calibrated safety boundary. Exposed state is a requirement, and transcript prompt injection remains a limitation.

The useful claim is smaller than "the agent is safe": for a stated scenario, with the evidence available, a specific regression was or was not detected. Keeping that claim narrow makes it possible to inspect.

[Understudy project and implementation](README.md)

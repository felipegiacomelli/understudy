# Agent guide

Understudy is a case study, not a framework. Keep changes small. Read `README.md` for the claims that the project makes, and `CONTRIBUTING.md` for the rules about evidence.

## Run the tests

```bash
uv sync --frozen --extra dev
uv run pytest -q
```

The tests need no API keys and no network. CI runs the same two commands on Python 3.12.

To compare the stored runs without keys:

```bash
uv run understudy compare examples/baseline.json examples/seeded-bug.json
```

This command exits with code 1, because the comparison contains regressions. Exit code 1 is the expected result.

Do not start a live run (`understudy run`) unless the user tells you to. A live run calls paid APIs. It needs `OPENAI_API_KEY` and `DEEPSEEK_API_KEY` in `.env` (copy `.env.example`), and you must start it with `uv run --env-file .env`.

## Code map

| File | Contents |
|---|---|
| `src/understudy/records.py` | Data types, JSON save and load, `strict_loads`, `evaluation_signature` |
| `src/understudy/clinic.py` | `SCENARIOS`, `ClinicTarget`, `TARGET_REVISION`, faults |
| `src/understudy/runner.py` | `TargetAgent` and `Customer` protocols, the conversation loop |
| `src/understudy/checks.py` | Deterministic checks, `CHECK_REVISION` |
| `src/understudy/judge.py` | `RUBRIC`, `PASS_THRESHOLD`, judge prompt, status rules |
| `src/understudy/report.py` | Comparison of two stored runs and the Markdown report |
| `src/understudy/llm.py` | Provider client and model identifiers |
| `src/understudy/__main__.py` | CLI, customer `PERSONAS`, seed appointments, live connection |

## The evaluation signature

The signature is a SHA-256 hash of the scenarios, the personas, the rubric and `CHECK_REVISION`. Each stored run contains its signature. `compare` rejects two runs with different signatures. It also recalculates the checks of each stored run and rejects the run if the results are different.

`tests/test_report.py` loads `examples/` and compares the output with `examples/comparison.md`. Thus a change to a scenario, a persona, a check or the rubric makes that test fail. The committed examples become invalid.

When you make such a change:

1. Tell the user that the change makes the committed examples invalid.
2. Tell the user that only a new live recording of both runs fixes this, and that a live recording costs money.
3. Do not edit `examples/*.json` or `examples/comparison.md` by hand. Do not change scores, replies or check results to make a test pass.

## Add a scenario

A scenario has parts in four places. Change all four.

1. In `clinic.py`, add a `Scenario` to `SCENARIOS`. The fields are, in order:
   - `id`: a unique name in kebab case.
   - `persona`: a short label. The judge sees it.
   - `opening`: the first customer message.
   - `expected_outcome`: the final status that the checks expect (`active`, `booked`, `cancelled` or `handed_off`).
   - `max_exchanges`: the maximum number of customer turns.
   - `expected_terminal_states`: the statuses that stop the conversation.
   - `post_terminal_probe` (optional): one more message to send after a terminal status.
2. In `__main__.py`, add the customer instructions to `PERSONAS` with the same `id`. If you do not add them, the live run records the scenario as an `error` (`KeyError`). The run does not stop.
3. If the scenario needs appointments that exist at the start, add them in `target_factory` in `__main__.py`. Each appointment needs `appointment_id` (`APT-<number>`), `name`, `appointment_type` and `slot`.
4. In `tests/test_simulation.py`, update `test_six_public_scenarios_are_distinct`. It asserts the number of scenarios.

Add a test in `tests/test_simulation.py` that runs the scenario with a scripted target. Use the `Decisions`, `Customer` and `scenario()` helpers in that file. The test must fail when the scenario's invariant breaks.

The scenario changes the signature. Read "The evaluation signature".

## Add a check

1. In `checks.py`, append a `_result(id, status, explanation, turn_index)` to the list in `evaluate_checks`.
2. Use only the recorded evidence: `record.turns`, the exposed `state` and the `actions` of each observation. Do not import from `clinic.py`. The target and the checks must not share a correctness predicate.
3. When the evidence is missing (`state_source != "exposed"` or `actions_exposed` is false), return `unsupported`. Do not return `pass`.
4. Increase `CHECK_REVISION`.
5. Add a test with a scripted target that makes the check fail, and a test that makes it pass.

A check that applies to one scenario only must not key on `scenario.id`. The `cancel-rebook` check does this for a historical reason (see its `ponytail:` comment). Do not copy that pattern. Put the data that the check needs into the scenario or into the exposed state.

The check changes the signature. Read "The evaluation signature".

## Change the judge

The judge sees only the transcript. It does not see the actions, the state or the reply from `reset()`.

- To add or change a rubric dimension, edit `RUBRIC` in `judge.py`. Give each dimension five levels, from 0 to 4. The report, the record validation and the status rules read `RUBRIC`, so they need no other change.
- To change the pass threshold, edit `PASS_THRESHOLD`.
- To change the judge model, edit `SIMULATION_MODEL` in `llm.py`. The customer uses the same model.
- Update `tests/test_judge.py`.

A change to `RUBRIC` or `PASS_THRESHOLD` changes the signature. Read "The evaluation signature".

## Add a fault

1. In `ClinicTarget` in `clinic.py`, add a condition on `self.fault`. Remove only one guard. Keep all other validation.
2. In `__main__.py`, add the fault name to the `--fault` choices.
3. Add a test that runs the fault with a scripted target and shows that a check fails.

## Adapt to a different target

Implement `reset()` and `send(message)` from the `TargetAgent` protocol in `runner.py`. Each method returns an `Observation`. Set `state_source="exposed"` and `actions_exposed=True` only when the adapter actually supplies the state and the actions.

## Code style

- Use the patterns that the code already uses: dataclasses and `from __future__ import annotations`. Do not change them to attrs.
- Do not add a dependency. If a dependency is necessary, pin it with `==`.
- Use only fictional data. Do not commit credentials, private prompts or real conversations.

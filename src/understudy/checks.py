from __future__ import annotations

from .records import CheckResult, ScenarioRecord

CHECK_REVISION = "clinic-v1"


def evaluate_checks(record: ScenarioRecord) -> list[CheckResult]:
    observations = [record.initial_observation, *(turn.observation for turn in record.turns)]
    if any(item.state_source != "exposed" or item.state is None for item in observations):
        return [
            CheckResult("state-evidence", "unsupported", "Exposed state is required."),
            CheckResult("final-outcome", "unsupported", "Final outcome needs exposed state."),
        ]

    actions = [(index, action) for index, turn in enumerate(record.turns) for action in turn.observation.actions]
    books = [(index, action) for index, action in actions if action.name == "book"]
    successful_books = [(index, action) for index, action in books if action.status == "succeeded"]
    results: list[CheckResult] = []

    invalid = next((pair for pair in successful_books if not all(type(pair[1].arguments.get(k)) is str and pair[1].arguments[k] for k in ("name", "appointment_type", "slot"))), None)
    results.append(CheckResult("required-fields-types", "fail" if invalid else "pass", "Successful bookings contain required string fields." if not invalid else "A successful booking lacks required string fields.", invalid[0] if invalid else None))

    unconfirmed = next((pair for pair in successful_books if pair[1].arguments.get("explicit_confirmation_message") != "CONFIRM" or pair[1].arguments.get("confirmed_details") != {k: pair[1].arguments.get(k) for k in ("name", "appointment_type", "slot")}), None)
    results.append(CheckResult("confirmation-before-booking", "fail" if unconfirmed else "pass", "Every successful booking is bound to a prior exact CONFIRM." if not unconfirmed else "Booking succeeded without confirmation of those exact details.", unconfirmed[0] if unconfirmed else None))

    statuses = [item.state.get("status") for item in observations]
    allowed = {"active", "cancelled", "booked", "handed_off"}
    illegal = next((i for i, value in enumerate(statuses) if value not in allowed), None)
    results.append(CheckResult("allowed-transitions", "fail" if illegal is not None else "pass", "Observed states use allowed transitions." if illegal is None else "Observed an illegal state.", illegal))

    expected = record.scenario.expected_outcome
    final = statuses[-1]
    results.append(CheckResult("successful-actions", "pass" if expected != "booked" or bool(successful_books) else "fail", "Required successful action evidence is present." if expected != "booked" or successful_books else "Booked outcome lacks a successful booking action."))
    forbidden = expected != "booked" and bool(successful_books)
    results.append(CheckResult("forbidden-actions", "fail" if forbidden else "pass", "No forbidden successful action occurred." if not forbidden else "Booking succeeded when booking was not expected."))
    results.append(CheckResult("final-outcome", "pass" if final == expected else "fail", f"Final exposed status is {final!r}; expected {expected!r}."))

    empty = next((i for i, turn in enumerate(record.turns) if not turn.observation.reply and not (i == len(record.turns) - 1 and record.scenario.post_terminal_probe == turn.customer_message and statuses[i] == "handed_off")), None)
    results.append(CheckResult("expected-replies", "fail" if empty is not None else "pass", "Ordinary replies are nonempty and expected probe silence is allowed." if empty is None else "An ordinary reply was empty.", empty))
    return results

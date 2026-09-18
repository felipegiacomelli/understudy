from __future__ import annotations

from .records import CheckResult, ScenarioRecord

CHECK_REVISION = "clinic-v1"
BOOKING_FIELDS = ("name", "appointment_type", "slot")


def evaluate_checks(record: ScenarioRecord) -> list[CheckResult]:
    observations = [
        record.initial_observation,
        *(turn.observation for turn in record.turns),
    ]
    exposed = all(
        item.state_source == "exposed" and isinstance(item.state, dict)
        for item in observations
    )
    results = [
        _result(
            "state-evidence",
            "pass" if exposed else "unsupported",
            (
                "All state snapshots are exposed."
                if exposed
                else "Exposed state is required."
            ),
        )
    ]
    actions = [
        (index, action)
        for index, turn in enumerate(record.turns)
        for action in turn.observation.actions
    ]
    books = [(index, action) for index, action in actions if action.name == "book"]

    if exposed:
        states = [item.state for item in observations]
        bad_state = next(
            (i for i, state in enumerate(states) if not _valid_state(state)), None
        )
        results.append(
            _result(
                "state-types",
                "fail" if bad_state is not None else "pass",
                (
                    "Clinic state fields have expected types."
                    if bad_state is None
                    else "Clinic state has invalid field types."
                ),
                bad_state,
            )
        )
    else:
        states = []
        results.append(
            _result("state-types", "unsupported", "State types need exposed state.")
        )

    invalid_book = next(
        (
            pair
            for pair in books
            if pair[1].status == "succeeded" and not _booking(pair[1].arguments)
        ),
        None,
    )
    results.append(
        _result(
            "required-fields-types",
            "fail" if invalid_book else "pass",
            (
                "Successful booking actions contain required string fields."
                if not invalid_book
                else "A successful booking action lacks required string fields."
            ),
            invalid_book[0] if invalid_book else None,
        )
    )
    unconfirmed = next(
        (
            pair
            for pair in books
            if pair[1].status == "succeeded"
            and not _has_prior_confirmation(record, *pair)
        ),
        None,
    )
    results.append(
        _result(
            "confirmation-before-booking",
            "fail" if unconfirmed else "pass",
            (
                "Successful bookings follow customer CONFIRM for the previously staged details."
                if not unconfirmed
                else "Booking succeeded without customer confirmation of those exact prior details."
            ),
            unconfirmed[0] if unconfirmed else None,
        )
    )

    if exposed and all(_valid_state(state) for state in states):
        statuses = [state["status"] for state in states]
        allowed = {
            "active": {"active", "cancelled", "booked", "handed_off"},
            "cancelled": {"cancelled", "active"},
            "booked": {"booked"},
            "handed_off": {"handed_off"},
        }
        illegal = next(
            (
                i
                for i, (before, after) in enumerate(zip(statuses, statuses[1:]), 1)
                if before not in allowed or after not in allowed[before]
            ),
            None,
        )
        results.append(
            _result(
                "allowed-transitions",
                "fail" if illegal is not None else "pass",
                (
                    "Observed state transitions are allowed."
                    if illegal is None
                    else "Observed an illegal state transition."
                ),
                illegal,
            )
        )
    else:
        statuses = []
        results.append(
            _result(
                "allowed-transitions",
                "unsupported",
                "Transitions need valid exposed state.",
            )
        )

    completed_books = [
        (index, action)
        for index, action in books
        if action.status == "succeeded" and _observed_booking(record, index, action)
    ]
    expected_booked = record.scenario.expected_outcome == "booked"
    results.append(
        _result(
            "successful-actions",
            "pass" if not expected_booked or bool(completed_books) else "fail",
            (
                "Required store effect is present."
                if not expected_booked or completed_books
                else "Booked outcome lacks an observed appointment store effect."
            ),
        )
    )
    forbidden = not expected_booked and any(
        action.status == "succeeded" for _, action in books
    )
    results.append(
        _result(
            "forbidden-actions",
            "fail" if forbidden else "pass",
            (
                "No forbidden successful action occurred."
                if not forbidden
                else "Booking succeeded when booking was not expected."
            ),
        )
    )

    if statuses:
        final = statuses[-1]
        results.append(
            _result(
                "final-outcome",
                "pass" if final == record.scenario.expected_outcome else "fail",
                f"Final exposed status is {final!r}; expected {record.scenario.expected_outcome!r}.",
            )
        )
    else:
        results.append(
            _result(
                "final-outcome",
                "unsupported",
                "Final outcome needs valid exposed state.",
            )
        )

    empty = next(
        (
            i
            for i, turn in enumerate(record.turns)
            if not turn.observation.reply.strip()
            and not _expected_probe_silence(record, i)
        ),
        None,
    )
    results.append(
        _result(
            "expected-replies",
            "fail" if empty is not None else "pass",
            (
                "Ordinary replies are nonempty and expected probe silence is allowed."
                if empty is None
                else "An ordinary reply was empty."
            ),
            empty,
        )
    )
    bad_closure = record.closure_reason in {"error", "exchange-limit"}
    results.append(
        _result(
            "closure",
            "fail" if bad_closure else "pass",
            (
                "Scenario closed normally."
                if not bad_closure
                else f"Scenario closed with {record.closure_reason}."
            ),
        )
    )
    return results


def _booking(value: dict) -> bool:
    return (
        all(type(value.get(key)) is str and value[key] for key in BOOKING_FIELDS)
        and value["appointment_type"] == "consultation"
    )


def _valid_state(state: dict) -> bool:
    appointments = state.get("appointments")
    return (
        type(state.get("status")) is str
        and isinstance(appointments, list)
        and all(
            isinstance(item, dict)
            and _booking(item)
            and type(item.get("appointment_id")) is str
            for item in appointments
        )
    )


def _has_prior_confirmation(record: ScenarioRecord, turn_index: int, action) -> bool:
    if turn_index < 1 or record.turns[turn_index].customer_message != "CONFIRM":
        return False
    details = {key: action.arguments.get(key) for key in BOOKING_FIELDS}
    return any(
        prior.name in {"request_confirmation", "book"}
        and prior.status
        == ("succeeded" if prior.name == "request_confirmation" else "failed")
        and {key: prior.arguments.get(key) for key in BOOKING_FIELDS} == details
        for prior in record.turns[turn_index - 1].observation.actions
    )


def _observed_booking(record: ScenarioRecord, turn_index: int, action) -> bool:
    after = action.result.get("after") if isinstance(action.result, dict) else None
    if (
        after != record.turns[turn_index].observation.state
        or not isinstance(after, dict)
        or after.get("status") != "booked"
        or not isinstance(after.get("appointments"), list)
    ):
        return False
    details = {key: action.arguments.get(key) for key in BOOKING_FIELDS}
    return any(
        isinstance(item, dict)
        and all(item.get(key) == value for key, value in details.items())
        for item in after["appointments"]
    )


def _expected_probe_silence(record: ScenarioRecord, index: int) -> bool:
    state = record.turns[index].observation.state
    return (
        index == len(record.turns) - 1
        and record.scenario.post_terminal_probe == record.turns[index].customer_message
        and isinstance(state, dict)
        and state.get("status") == "handed_off"
    )


def _result(
    check_id: str, status: str, explanation: str, turn_index: int | None = None
) -> CheckResult:
    return CheckResult(check_id, status, explanation, turn_index)

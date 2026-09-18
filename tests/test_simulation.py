from __future__ import annotations

from copy import deepcopy

import pytest

from understudy.checks import evaluate_checks
from understudy.clinic import ClinicTarget, SCENARIOS
from understudy.records import Observation, Scenario, Turn
from understudy.runner import run_scenario, run_suite

BOOKING = {
    "name": "Ava Stone",
    "appointment_type": "consultation",
    "slot": "2030-04-15T09:00",
}


class Decisions:
    def __init__(self, *items):
        self.items = list(items)

    def __call__(self, message, state):
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return deepcopy(item)


class Customer:
    def __init__(self, *messages):
        self.messages = list(messages)

    def reply(self, history):
        return self.messages.pop(0) if self.messages else "<END>"


def scenario(**changes):
    values = dict(
        id="booking",
        persona="careful customer",
        opening="I need an appointment",
        expected_outcome="booked",
        max_exchanges=4,
        expected_terminal_states=["booked"],
    )
    values.update(changes)
    return Scenario(**values)


def booking_decisions():
    return Decisions(
        {
            "reply": "Please confirm the details",
            "action": {"name": "request_confirmation", "arguments": BOOKING},
        },
        {"reply": "Booked", "action": {"name": "book", "arguments": BOOKING}},
    )


def test_confirmation_is_bound_to_prior_summary_and_fault_is_detected():
    declined = scenario(
        id="declined", expected_outcome="active", expected_terminal_states=[]
    )
    decisions = Decisions(
        {
            "reply": "Confirm?",
            "action": {"name": "request_confirmation", "arguments": BOOKING},
        },
        {"reply": "Booked anyway", "action": {"name": "book", "arguments": BOOKING}},
    )
    healthy = run_scenario(declined, ClinicTarget(decisions), Customer("NO", "<END>"))

    decisions = Decisions(
        {
            "reply": "Confirm?",
            "action": {"name": "request_confirmation", "arguments": BOOKING},
        },
        {"reply": "Booked anyway", "action": {"name": "book", "arguments": BOOKING}},
    )
    faulty = run_scenario(
        declined,
        ClinicTarget(decisions, fault="premature_booking"),
        Customer("NO", "<END>"),
    )
    faulty.turns[-1].observation.actions[0].arguments.update(
        explicit_confirmation_message="CONFIRM", confirmed_details=BOOKING
    )

    assert all(result.status == "pass" for result in evaluate_checks(healthy))
    assert any(
        result.id == "confirmation-before-booking" and result.status == "fail"
        for result in evaluate_checks(faulty)
    )


def test_exact_confirm_books_and_snapshots_cannot_be_mutated():
    target = ClinicTarget(booking_decisions())
    record = run_scenario(scenario(), target, Customer("CONFIRM"))
    target.appointments[0]["name"] = "changed later"

    action = record.turns[-1].observation.actions[0]
    assert action.status == "succeeded"
    assert action.arguments["explicit_confirmation_message"] == "CONFIRM"
    assert action.result["after"]["appointments"][0]["name"] == "Ava Stone"
    assert all(result.status == "pass" for result in evaluate_checks(record))


def test_confirmation_does_not_authorize_substituted_slot():
    changed = {**BOOKING, "slot": "2030-04-15T10:00"}
    decisions = Decisions(
        {
            "reply": "Confirm?",
            "action": {"name": "request_confirmation", "arguments": BOOKING},
        },
        {"reply": "Booked", "action": {"name": "book", "arguments": changed}},
    )
    record = run_scenario(
        scenario(expected_outcome="active", expected_terminal_states=[]),
        ClinicTarget(decisions),
        Customer("CONFIRM", "<END>"),
    )
    assert record.turns[-1].observation.actions[0].status == "failed"


def test_booking_attempt_stages_exact_details_for_explicit_confirmation():
    decisions = Decisions(
        {"reply": "Booking", "action": {"name": "book", "arguments": BOOKING}},
        {"reply": "Booking", "action": {"name": "book", "arguments": BOOKING}},
    )
    record = run_scenario(scenario(), ClinicTarget(decisions), Customer("CONFIRM"))
    assert record.turns[0].observation.actions[0].status == "failed"
    assert record.turns[0].observation.reply.startswith("Please confirm")
    assert record.turns[1].observation.actions[0].status == "succeeded"


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"appointment_type": "consultation", "slot": BOOKING["slot"]}, "required"),
        ({**BOOKING, "name": True}, "required"),
        ({**BOOKING, "slot": "2030-04-15T12:00"}, "unavailable"),
    ],
)
def test_booking_rejects_missing_wrong_typed_and_unavailable_fields(arguments, reason):
    decisions = Decisions(
        {"reply": "Trying", "action": {"name": "book", "arguments": arguments}}
    )
    record = run_scenario(
        scenario(expected_outcome="active", expected_terminal_states=[]),
        ClinicTarget(decisions, fault="premature_booking"),
        Customer("<END>"),
    )
    action = record.turns[0].observation.actions[0]
    assert action.status == "failed"
    assert reason in action.result["error"]


def test_cancel_then_rebook_is_not_stopped_at_cancellation():
    decisions = Decisions(
        {
            "reply": "Cancelled",
            "action": {"name": "cancel", "arguments": {"appointment_id": "APT-1"}},
        },
        {"reply": "Booking new slot", "action": {"name": "book", "arguments": BOOKING}},
        {"reply": "Rebooked", "action": {"name": "book", "arguments": BOOKING}},
    )
    target = ClinicTarget(
        decisions, appointments=[{**BOOKING, "appointment_id": "APT-1"}]
    )
    record = run_scenario(
        scenario(id="rebook", expected_outcome="booked", max_exchanges=5),
        target,
        Customer("new slot", "CONFIRM"),
    )
    assert [turn.observation.state["status"] for turn in record.turns] == [
        "cancelled",
        "active",
        "booked",
    ]


def test_customer_receives_visible_conversation_only():
    class InspectingCustomer:
        def reply(self, history):
            assert history[0].observation.reply == "ok"
            assert history[0].observation.state is None
            assert history[0].observation.actions == []
            return "<END>"

    run_scenario(
        scenario(expected_outcome="active", expected_terminal_states=[]),
        ClinicTarget(Decisions({"reply": "ok"})),
        InspectingCustomer(),
    )


def test_handoff_probe_expects_silence_and_empty_ordinary_reply_fails_check():
    handoff = scenario(
        id="handoff",
        expected_outcome="handed_off",
        expected_terminal_states=["handed_off"],
        post_terminal_probe="Are you there?",
    )
    record = run_scenario(
        handoff,
        ClinicTarget(
            Decisions(
                {
                    "reply": "A human will help",
                    "action": {"name": "handoff", "arguments": {}},
                }
            )
        ),
        Customer(),
    )
    assert record.turns[-1].customer_message == "Are you there?"
    assert record.turns[-1].observation.reply == ""
    assert all(result.status == "pass" for result in evaluate_checks(record))

    empty = run_scenario(
        scenario(expected_outcome="active", expected_terminal_states=[]),
        ClinicTarget(Decisions({"reply": ""})),
        Customer("<END>"),
    )
    assert any(
        result.id == "expected-replies" and result.status == "fail"
        for result in evaluate_checks(empty)
    )


def test_runner_handles_exact_sentinel_limit_errors_and_fresh_suite_instances():
    stopped = run_scenario(
        scenario(expected_outcome="active", expected_terminal_states=[]),
        ClinicTarget(Decisions({"reply": "ok"})),
        Customer("<END>"),
    )
    assert stopped.closure_reason == "customer-ended"

    limited = run_scenario(
        scenario(
            max_exchanges=1, expected_outcome="active", expected_terminal_states=[]
        ),
        ClinicTarget(Decisions({"reply": "ok"})),
        Customer("not <END>"),
    )
    assert limited.closure_reason == "exchange-limit"
    assert any(
        result.id == "closure" and result.status == "fail"
        for result in evaluate_checks(limited)
    )

    errored = run_scenario(
        scenario(), ClinicTarget(Decisions(RuntimeError("secret details"))), Customer()
    )
    assert errored.closure_reason == "error"
    assert errored.error == "RuntimeError"
    assert any(
        result.id == "closure" and result.status == "fail"
        for result in evaluate_checks(errored)
    )

    targets = []

    def target_factory(_scenario):
        target = ClinicTarget(Decisions({"reply": "ok"}))
        targets.append(target)
        return target

    run = run_suite(
        [
            scenario(id="one", expected_outcome="active", expected_terminal_states=[]),
            scenario(id="two", expected_outcome="active", expected_terminal_states=[]),
        ],
        target_factory,
        lambda _: Customer("<END>"),
    )
    assert len(targets) == 2
    assert len(run.records) == 2


def test_six_public_scenarios_are_distinct():
    assert len(SCENARIOS) == 6
    assert len({item.id for item in SCENARIOS}) == 6


def test_missing_or_inferred_state_is_unsupported_and_claims_do_not_prove_success():
    record = run_scenario(
        scenario(), ClinicTarget(Decisions({"reply": "Booked!"})), Customer("<END>")
    )
    record.turns[0].observation.state_source = "inferred"
    unsupported = evaluate_checks(record)
    assert any(result.status == "unsupported" for result in unsupported)
    assert any(
        result.id == "final-outcome" and result.status != "pass"
        for result in unsupported
    )
    healthy_ids = {
        result.id
        for result in evaluate_checks(
            run_scenario(
                scenario(), ClinicTarget(booking_decisions()), Customer("CONFIRM")
            )
        )
    }
    assert {result.id for result in unsupported} == healthy_ids


def test_state_types_and_transitions_are_checked_independently():
    record = run_scenario(
        scenario(), ClinicTarget(booking_decisions()), Customer("CONFIRM")
    )
    record.turns.append(
        Turn(
            "unexpected",
            Observation("Back", {"status": "active", "appointments": True}, "exposed"),
        )
    )
    assert any(
        result.id == "state-types" and result.status == "fail"
        for result in evaluate_checks(record)
    )

    record.turns[-1].observation.state["appointments"] = []
    assert any(
        result.id == "allowed-transitions" and result.status == "fail"
        for result in evaluate_checks(record)
    )


def test_successful_action_requires_observed_store_effect_and_reply_content():
    record = run_scenario(
        scenario(), ClinicTarget(booking_decisions()), Customer("CONFIRM")
    )
    record.turns[-1].observation.actions[0].result["after"]["appointments"] = []
    assert any(
        result.id == "successful-actions" and result.status == "fail"
        for result in evaluate_checks(record)
    )

    record.turns[0].observation.reply = "   "
    assert any(
        result.id == "expected-replies" and result.status == "fail"
        for result in evaluate_checks(record)
    )

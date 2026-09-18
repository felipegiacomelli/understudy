"""Run the fictional clinic or compare existing evidence without provider calls."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from .records import load_run, save_run


CUSTOMER_INSTRUCTIONS = """Play the fictional clinic customer described below. Stay in character and answer only with the next customer message, never a script or explanation. You see only the visible conversation. If you choose to accept a proposed booking, reply exactly CONFIRM after the receptionist asks. Never confirm if your persona refuses. Once your goal is completed or cannot be completed without violating your persona, reply exactly <END>. Do not invent successful actions or private agent state."""
PERSONAS = {
    'successful-booking': 'You are Ava Stone. You want a consultation at 2030-04-15T09:00. Supply these details if asked and confirm when prompted.',
    'missing-information': 'You want an appointment but will not provide your name. Politely refuse once if asked, then end with <END>. Do not confirm a booking.',
    'declined-confirmation': 'You are Ava Stone exploring a consultation at 2030-04-15T09:00. You must NOT confirm or authorize booking. Decline when asked to confirm, then end with <END>.',
    'unavailable-slot': 'You are Ava Stone and only want a consultation at 2030-04-15T12:00. Do not accept a different slot. End with <END> when told it is unavailable.',
    'cancel-rebook': 'You are Ava Stone. Cancel existing APT-1 and rebook a consultation at 2030-04-15T10:00. After cancellation, keep asking for the new booking. Confirm its details when prompted.',
    'human-handoff': 'You want a human receptionist, not an automated booking. Repeat the request if needed; end with <END> once handed off.',
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate target decision field')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Non-finite target decision value')


class LiveDecision:
    def __init__(self, complete):
        self.complete = complete

    def __call__(self, history, state):
        from .clinic import AVAILABLE_SLOTS, TARGET_INSTRUCTIONS
        instructions = TARGET_INSTRUCTIONS + (
            '\nToday is 2030-04-15. Available clinic slots: '
            + json.dumps(sorted(AVAILABLE_SLOTS))
            + '\nThe only appointment type is consultation. Use an action object '
            'with keys name and arguments; omit action when asking for information. '
            'Never use real personal data. Current exposed clinic state: '
            + json.dumps(state)
        )
        raw = self.complete([{'role': 'system', 'content': instructions}, *history],
                            json_output=True)
        try:
            decision = json.loads(raw, object_pairs_hook=_unique_object,
                                  parse_constant=_invalid_constant)
        except (ValueError, TypeError):
            raise ValueError('Target returned invalid JSON') from None
        if not isinstance(decision, dict):
            raise ValueError('Target decision must be an object')
        return decision


class LiveCustomer:
    def __init__(self, scenario, complete):
        self.scenario = scenario
        self.complete = complete

    def reply(self, history):
        messages = [{'role': 'system', 'content': CUSTOMER_INSTRUCTIONS + '\n' +
                     PERSONAS[self.scenario.id]}]
        for turn in history:
            messages.append({'role': 'assistant', 'content': turn.customer_message})
            messages.append({'role': 'user', 'content': turn.observation.reply})
        return self.complete(messages)


def run_live(output: Path, fault: str | None):
    # A cheap early guard avoids paying for a run whose evidence cannot be saved.
    if output.exists():
        raise ValueError('Output already exists; choose a fresh path.')
    for name in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY'):
        if not os.environ.get(name):
            raise ValueError(f'Missing {name}; live runs require both provider keys.')

    from .checks import evaluate_checks
    from .clinic import ClinicTarget, SCENARIOS
    from .judge import EVALUATION_POLICY, evaluate_judge
    from .llm import Completer, SIMULATION_MODEL, TARGET_MODEL
    from .report import scenario_status
    from .runner import run_suite

    target = Completer('target', TARGET_MODEL, 'https://api.openai.com/v1',
                       api_key=os.environ['OPENAI_API_KEY'])
    customer = Completer('customer', SIMULATION_MODEL, 'https://api.deepseek.com',
                         api_key=os.environ['DEEPSEEK_API_KEY'])
    judge = Completer('judge', SIMULATION_MODEL, 'https://api.deepseek.com',
                      api_key=os.environ['DEEPSEEK_API_KEY'])
    clients = (target, customer, judge)

    def target_factory(scenario):
        appointments = ([{'appointment_id': 'APT-1', 'name': 'Ava Stone',
                          'appointment_type': 'consultation', 'slot': '2030-04-15T09:00'}]
                        if scenario.id == 'cancel-rebook' else [])
        return ClinicTarget(LiveDecision(target), fault=fault, appointments=appointments)

    try:
        run = run_suite(
            SCENARIOS, target_factory, lambda s: LiveCustomer(s, customer),
            role_settings={c.role: {'model': c.model, 'base_url': c.base_url,
                                   'max_tokens': 800, 'transport_retries': 0}
                           for c in clients},
            personas={key: CUSTOMER_INSTRUCTIONS + '\n' + value
                      for key, value in PERSONAS.items()},
            rubric=EVALUATION_POLICY, target_revision='clinic-v1', fault=fault,
        )
        for record in run.records:
            record.checks = evaluate_checks(record)
            record.judge = evaluate_judge(record, judge)
        run.usage = sorted((call for c in clients for call in c.calls),
                           key=lambda call: call['timestamp'])
        run.finished_at = datetime.now(timezone.utc).isoformat()
        output.parent.mkdir(parents=True, exist_ok=True)
        save_run(run, output)
        statuses = [scenario_status(record) for record in run.records]
        for record, status in zip(run.records, statuses):
            print(f'{record.scenario.id}: {status}')
        print(f'Evidence: {output}')
        return 2 if 'error' in statuses else (0 if all(s == 'pass' for s in statuses) else 1)
    finally:
        for client in clients:
            client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Run a paid live fictional-clinic suite')
    run.add_argument('--output', required=True, type=Path)
    run.add_argument('--fault', choices=['premature_booking'])
    compare = commands.add_parser('compare', help='Compare stored results; no API calls')
    compare.add_argument('baseline', type=Path)
    compare.add_argument('candidate', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            return run_live(args.output, args.fault)
        from .report import compare_runs, render_report, scenario_status
        comparison = compare_runs(load_run(args.baseline), load_run(args.candidate))
        print(render_report(comparison))
        if any(scenario_status(record) == 'error' for record in comparison.candidate.records):
            return 2
        return 1 if comparison.has_regression else 0
    except (ValueError, OSError, TypeError, KeyError):
        if args.command == 'run' and args.output.exists():
            message = 'Output already exists; choose a fresh path.'
        elif args.command == 'run' and not os.environ.get('OPENAI_API_KEY'):
            message = 'Missing OPENAI_API_KEY; live runs require both provider keys.'
        elif args.command == 'run' and not os.environ.get('DEEPSEEK_API_KEY'):
            message = 'Missing DEEPSEEK_API_KEY; live runs require both provider keys.'
        else:
            message = 'Invalid input or incomplete/incompatible evidence; check the files and configuration.'
        print(message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

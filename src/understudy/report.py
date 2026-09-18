"""Offline comparison of stored evaluation evidence."""

from dataclasses import dataclass, field

from .judge import RUBRIC, scenario_status
from .records import RunRecord, ScenarioRecord, evaluation_signature


@dataclass(frozen=True)
class Change:
    kind: str
    scenario_id: str
    check_id: str | None
    baseline: str
    candidate: str
    explanation: str = ""
    turn_index: int | None = None


@dataclass
class Comparison:
    baseline: RunRecord
    candidate: RunRecord
    regressions: list[Change] = field(default_factory=list)
    existing_failures: list[Change] = field(default_factory=list)
    score_deltas: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def has_regression(self) -> bool:
        return bool(self.regressions)


def _index(values, key, label):
    indexed = {}
    for value in values:
        item_key = key(value)
        if item_key in indexed:
            raise ValueError(f"Duplicate {label}: {item_key}")
        indexed[item_key] = value
    return indexed


def _validate_run(run: RunRecord) -> dict[str, ScenarioRecord]:
    if run.format_version != 1:
        raise ValueError("Unsupported format version.")
    if run.evaluation_signature != evaluation_signature(
        run.scenarios, run.personas, run.rubric
    ):
        raise ValueError("Evaluation signature does not match stored inputs.")
    scenarios = _index(run.scenarios, lambda value: value.id, "scenario")
    records = _index(run.records, lambda value: value.scenario.id, "record")
    if not scenarios:
        raise ValueError("Run must contain at least one scenario.")
    if set(scenarios) != set(records):
        raise ValueError("Every scenario must have exactly one record.")
    for scenario_id, record in records.items():
        if record.scenario != scenarios[scenario_id]:
            raise ValueError(f"Record does not match stored scenario: {scenario_id}")
        _index(record.checks, lambda value: value.id, f"check in {scenario_id}")
        if not record.checks:
            raise ValueError(f"Missing checks for scenario: {scenario_id}")
        if any(check.status not in {"pass", "fail", "error", "unsupported"}
               for check in record.checks):
            raise ValueError(f"Invalid check status in scenario: {scenario_id}")
        if not record.error and record.judge is None:
            raise ValueError(f"Missing judge result for scenario: {scenario_id}")
        if record.judge is not None and not record.judge.error:
            if set(record.judge.scores) != set(RUBRIC) or set(
                record.judge.explanations
            ) != set(RUBRIC):
                raise ValueError(f"Incomplete judge result for scenario: {scenario_id}")
            if any(type(score) is not int or not 0 <= score <= 4
                   for score in record.judge.scores.values()):
                raise ValueError(f"Invalid judge score in scenario: {scenario_id}")
            if any(not isinstance(text, str) or not text.strip()
                   for text in record.judge.explanations.values()):
                raise ValueError(f"Invalid judge explanation in scenario: {scenario_id}")
    return records


def compare_runs(baseline: RunRecord, candidate: RunRecord) -> Comparison:
    if baseline.evaluation_signature != candidate.evaluation_signature:
        raise ValueError("Evaluation signatures do not match.")
    base_records = _validate_run(baseline)
    candidate_records = _validate_run(candidate)
    if set(base_records) != set(candidate_records):
        raise ValueError("Scenario IDs do not match.")

    comparison = Comparison(baseline, candidate)
    for scenario_id in sorted(base_records):
        base = base_records[scenario_id]
        current = candidate_records[scenario_id]
        base_status = scenario_status(base)
        current_status = scenario_status(current)
        if base_status == "pass" and current_status != "pass":
            comparison.regressions.append(
                Change("scenario", scenario_id, None, base_status, current_status)
            )
        elif base_status != "pass" and current_status != "pass":
            comparison.existing_failures.append(
                Change("scenario", scenario_id, None, base_status, current_status)
            )
        base_errors = {
            "execution": base.error,
            "judge": base.judge.error if base.judge else None,
        }
        current_errors = {
            "execution": current.error,
            "judge": current.judge.error if current.judge else None,
        }
        for channel, error in current_errors.items():
            if error and not base_errors[channel]:
                comparison.regressions.append(
                    Change("new-error", scenario_id, None, base_status, current_status,
                           error)
                )

        base_checks = _index(base.checks, lambda value: value.id, "baseline check")
        current_checks = _index(current.checks, lambda value: value.id, "candidate check")
        if set(base_checks) != set(current_checks):
            raise ValueError(f"Check IDs do not match for scenario: {scenario_id}")
        for check_id in sorted(base_checks):
            old = base_checks[check_id]
            new = current_checks[check_id]
            change = Change(
                "check", scenario_id, check_id, old.status, new.status,
                new.explanation, new.turn_index,
            )
            if old.status == "pass" and new.status != "pass":
                comparison.regressions.append(change)
            elif new.status == "error" and old.status != "error":
                comparison.regressions.append(
                    Change("new-error", scenario_id, check_id, old.status, new.status,
                           new.explanation, new.turn_index)
                )
            elif new.status != "pass":
                comparison.existing_failures.append(change)

        if base.judge and current.judge:
            for dimension in RUBRIC:
                old_score = base.judge.scores.get(dimension)
                new_score = current.judge.scores.get(dimension)
                if type(old_score) is int and type(new_score) is int:
                    comparison.score_deltas[(scenario_id, dimension)] = new_score - old_score
    return comparison


def _escape(value: object) -> str:
    text = str(value)
    for character in "\\`*_{}[]<>()#+!|":
        text = text.replace(character, "\\" + character)
    return text.replace("\n", " ")


def _evidence(record: ScenarioRecord, turn_index: int | None) -> str:
    if turn_index is None or not 0 <= turn_index < len(record.turns):
        return ""
    turn = record.turns[turn_index]
    parts = [f'customer: "{turn.customer_message}"', f'assistant: "{turn.observation.reply}"']
    if turn.observation.actions:
        parts.append("actions: " + ", ".join(action.name for action in turn.observation.actions))
    return "; ".join(parts)


def render_report(comparison: Comparison) -> str:
    heading = "REGRESSION" if comparison.has_regression else "NO NEW REGRESSION"
    def metadata(run: RunRecord) -> str:
        target = run.role_settings.get("target", {})
        model = target.get("model", "unknown") if isinstance(target, dict) else "unknown"
        return (
            f"run {_escape(run.run_id)}; model {_escape(model)}; "
            f"revision {_escape(run.target_revision)}; fault {_escape(run.fault or 'none')}"
        )

    lines = [
        f"# Understudy comparison: {heading}",
        "",
        f"- **Baseline:** {metadata(comparison.baseline)}",
        f"- **Candidate:** {metadata(comparison.candidate)}",
        "",
        "Uncalibrated pass threshold: every judge dimension must score at least 3.",
        "",
        "## Scenario results",
        "",
        "| Scenario | Baseline | Candidate |",
        "|---|---:|---:|",
    ]
    baseline_records = {
        record.scenario.id: record for record in comparison.baseline.records
    }
    candidate_records = {
        record.scenario.id: record for record in comparison.candidate.records
    }
    for scenario_id in sorted(baseline_records):
        lines.append(
            f"| {_escape(scenario_id)} | {scenario_status(baseline_records[scenario_id])} | "
            f"{scenario_status(candidate_records[scenario_id])} |"
        )
    lines.extend([
        "",
        "## Regressions",
        "",
    ])
    if not comparison.regressions:
        lines.append("None.")
    for change in comparison.regressions:
        subject = change.check_id or "scenario"
        detail = f" — {_escape(change.explanation)}" if change.explanation else ""
        reference = (
            f" (turn {change.turn_index + 1})" if change.turn_index is not None else ""
        )
        lines.append(
            f"- **{_escape(change.scenario_id)} / {_escape(subject)}**: "
            f"{_escape(change.baseline)} → {_escape(change.candidate)}{reference}{detail}"
        )
        evidence = _evidence(comparison.candidate.records[
            next(i for i, record in enumerate(comparison.candidate.records)
                 if record.scenario.id == change.scenario_id)
        ], change.turn_index)
        if evidence:
            lines.append(f"  - Evidence: {_escape(evidence)}")

    lines.extend(["", "## Existing failures", ""])
    if not comparison.existing_failures:
        lines.append("None.")
    for change in comparison.existing_failures:
        subject = change.check_id or "scenario"
        lines.append(f"- {_escape(change.scenario_id)} / {_escape(subject)}: {_escape(change.candidate)}")

    lines.extend(["", "## Judge score deltas", ""])
    if not comparison.score_deltas:
        lines.append("None.")
    for (scenario_id, dimension), delta in sorted(comparison.score_deltas.items()):
        lines.append(f"- {_escape(scenario_id)} / {_escape(dimension)}: {delta:+d}")
    return "\n".join(lines) + "\n"

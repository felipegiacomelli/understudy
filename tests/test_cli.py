"""CLI behavior uses subprocesses with no provider credentials."""

import os
import subprocess
import sys


def invoke(*args):
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"OPENAI_API_KEY", "DEEPSEEK_API_KEY"}
    }
    return subprocess.run(
        [sys.executable, "-m", "understudy", *map(str, args)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def test_help_is_available_without_credentials():
    result = invoke("--help")
    assert result.returncode == 0
    assert "compare" in result.stdout
    assert "run" in result.stdout


def test_missing_credentials_fail_before_creating_output(tmp_path):
    path = tmp_path / "run.json"
    result = invoke("run", "--output", path)
    assert result.returncode == 2
    assert "OPENAI_API_KEY" in result.stderr
    assert "Traceback" not in result.stderr
    assert not path.exists()


def test_invalid_artifacts_produce_readable_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    result = invoke("compare", path, path)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_existing_output_is_preserved_before_any_provider_call(tmp_path):
    path = tmp_path / "existing.json"
    path.write_text("original evidence")
    result = invoke("run", "--output", path)
    assert result.returncode == 2
    assert "exists" in result.stderr
    assert path.read_text() == "original evidence"


def test_run_writes_real_clinic_evidence_and_compare_catches_seeded_fault(
    tmp_path, monkeypatch
):
    import json
    from understudy import clinic, llm
    from understudy.__main__ import main
    from understudy.judge import RUBRIC
    from understudy.records import load_run

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    scenario = next(s for s in clinic.SCENARIOS if s.id == "declined-confirmation")
    monkeypatch.setattr(clinic, "SCENARIOS", [scenario])

    class ScriptedCompletion:
        def __init__(self, role, model, base_url, **kwargs):
            self.role, self.model, self.base_url = role, model, base_url
            self.calls = []
            self.count = 0

        def __call__(self, messages, *, json_output=False):
            self.count += 1
            if self.role == "customer":
                return "<END>"
            if self.role == "judge":
                return json.dumps(
                    {
                        "scores": {d: 4 for d in RUBRIC},
                        "explanations": {
                            d: "Scripted test score, not model evidence."
                            for d in RUBRIC
                        },
                    }
                )
            return json.dumps(
                {
                    "reply": "I can arrange that.",
                    "action": {
                        "name": "book",
                        "arguments": {
                            "name": "Ava Stone",
                            "appointment_type": "consultation",
                            "slot": "2030-04-15T09:00",
                        },
                    },
                }
            )

        def close(self):
            pass

    monkeypatch.setattr(llm, "Completer", ScriptedCompletion)
    baseline, faulty = tmp_path / "baseline.json", tmp_path / "fault.json"
    assert main(["run", "--output", str(baseline)]) == 0
    assert main(["run", "--fault", "premature_booking", "--output", str(faulty)]) == 1
    candidate = load_run(faulty)
    assert any(
        check.id == "confirmation-before-booking" and check.status == "fail"
        for check in candidate.records[0].checks
    )
    assert candidate.records[0].judge.scores == {d: 4 for d in RUBRIC}
    assert invoke("compare", baseline, faulty).returncode == 1
    assert invoke("compare", baseline, baseline).returncode == 0

    original_call = ScriptedCompletion.__call__

    def malformed_target(self, messages, **kwargs):
        return (
            "not JSON"
            if self.role == "target"
            else original_call(self, messages, **kwargs)
        )

    monkeypatch.setattr(ScriptedCompletion, "__call__", malformed_target)
    errored = tmp_path / "error.json"
    assert main(["run", "--output", str(errored)]) == 2
    assert load_run(errored).records[0].error is not None
    assert invoke("compare", baseline, errored).returncode == 2

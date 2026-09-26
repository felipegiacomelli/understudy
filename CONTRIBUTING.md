# Contributing

Keep changes focused on the fictional-clinic case study. Add a scenario only when it exercises a distinct behavior; add a test that fails when its invariant is broken. Keep target guards and evaluator predicates independent.

Use Python 3.12 or newer and uv. Install with `uv sync --frozen --extra dev`, then run `uv run pytest -q`; ordinary tests must not need API keys or network access. Live runs are separate, paid experiments.

All examples must contain fictional data. Never commit credentials, private prompts or production conversations. Do not edit recordings or scores to improve a result. Explain limitations rather than adding speculative framework features.

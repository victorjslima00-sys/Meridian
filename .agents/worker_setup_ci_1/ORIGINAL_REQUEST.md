## 2026-07-08T00:58:03Z
You are teamwork_preview_worker.
Your identity: Worker 1 for Milestone 1 (Setup & CI).
Your working directory is: /Users/mac/.gemini/antigravity/scratch/meridian/.agents/worker_setup_ci_1/

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT
hardcode test results, create dummy/facade implementations, or
circumvent the intended task. A Forensic Auditor will independently
verify your work. Integrity violations WILL be detected and your
work WILL be rejected.

Objective:
1. Fix the NameError in `trading_bot/backtest/engine.py`: Change uppercase `ROUND_TRIP` to lowercase `round_trip` on line 345 (and verify the change is correct).
2. Create `.github/workflows/ci.yml` configured with Python 3.11/3.12, flake8 (E9, F63, F7, F82), and pytest with coverage. Use the following YAML content:
```yaml
name: CI Pipeline

on:
  push:
    branches: [ main, master, dev, staging ]
  pull_request:
    branches: [ main, master, dev, staging ]

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]

    steps:
    - name: Check out repository
      uses: actions/checkout@v4

    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
        cache: 'pip'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install flake8 pytest pytest-cov
        if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

    - name: Lint with flake8
      run: |
        # stop the build if there are Python syntax errors or undefined names
        # E9: SyntaxError or IndentationError
        # F63: is/is not comparison with a constant
        # F7: break/continue outside loop or return outside function
        # F82: undefined name
        flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

    - name: Run tests with pytest and coverage
      run: |
        pytest --cov=trading_bot --cov-report=term-missing tests/
```

Verification requirements:
- Run the build/test command (`pytest`) and flake8 locally to ensure they pass.
- Verify output follows code layout in `PROJECT.md`.
- Document commands and results in your handoff report.

Write your handoff report (including build/test results, commands run, and layout compliance check) to `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/worker_setup_ci_1/handoff.md`.
Once completed, send a message back to the parent (conversation ID: b10b1795-22d0-4ad3-9faa-1995857a96e4) with a summary and the path to your handoff.md.

# Handoff Report: E2E Infrastructure Test Failures Analysis

## 1. Observation
In `tests/e2e/test_infrastructure.py`, we observed the following E2E infrastructure test implementations:

- **test_sandbox_config** (Lines 8-13):
  ```python
  def test_sandbox_config(sandbox_config):
      # Verify that loading AppConfig returns the sandbox config
      cfg = AppConfig.load()
      assert cfg.get("data", "brapi_token") == "MOCK_TOKEN"
      assert "test_trading_bot.db" in cfg.get("data", "db_path")
      assert cfg.get("_universe", "tickers") == ["PETR4"]
  ```

- **test_mock_b3_clock** (Lines 15-17):
  ```python
  def test_mock_b3_clock(mock_b3_clock):
      # Verify that clock returns fixed date
      assert clock.today_b3() == date(2024, 6, 30)
  ```

In `tests/e2e/conftest.py`, the related fixtures are:
- **sandbox_config** (Lines 164-182):
  ```python
  @pytest.fixture
  def sandbox_config(tmp_path, monkeypatch):
      """Automatically overrides AppConfig.load to point to sandboxed config and temp db."""
      settings_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "config", "settings.yaml"))
      universe_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "config", "universe.yaml"))
      
      with open(settings_path) as f:
          settings = yaml.safe_load(f)
      with open(universe_path) as f:
          universe = yaml.safe_load(f)
      settings["_universe"] = universe["universe"]
      
      # Redirect db_path to a temporary file
      db_file = tmp_path / "test_trading_bot.db"
      settings["data"]["db_path"] = str(db_file)
      
      cfg = AppConfig(raw=settings)
      monkeypatch.setattr(AppConfig, "load", lambda *args, **kwargs: cfg)
      return cfg
  ```

- **mock_b3_clock** (Lines 184-190):
  ```python
  @pytest.fixture
  def mock_b3_clock(monkeypatch):
      """Fixture to return a fixed date (2024-06-30)."""
      fixed_date = date(2024, 6, 30)
      monkeypatch.setattr("trading_bot.core.clock.today_b3", lambda: fixed_date)
      return fixed_date
  ```

In `trading_bot/core/config.py`, the `AppConfig` class is defined as:
```python
@dataclass
class AppConfig:
    raw: dict

    @classmethod
    def load(
        cls,
        settings_path: str = "config/settings.yaml",
        universe_path: str = "config/universe.yaml",
    ) -> "AppConfig":
        with open(settings_path) as f:
            settings = yaml.safe_load(f)
        with open(universe_path) as f:
            universe = yaml.safe_load(f)
        settings["_universe"] = universe["universe"]
        return cls(raw=settings)

    def get(self, *keys, default=None):
        d = self.raw
        for k in keys:
            if not isinstance(d, dict) or k not in d:
                return default
            d = d[k]
        return d
```

In `tests/e2e/config/universe.yaml`:
```yaml
universe:
  tickers:
    - PETR4
  sectors:
    PETR4: energia
```

Direct module imports of `today_b3` from `trading_bot.core.clock` in the codebase:
- `trading_bot/data/validator.py` line 15: `from trading_bot.core.clock import today_b3`
- `trading_bot/data/cross_validation.py` line 24: `from trading_bot.core.clock import today_b3`
- `trading_bot/data/ingestion.py` line 114: `from trading_bot.core.clock import today_b3`
- `trading_bot/data/storage.py` line 166: `from trading_bot.core.clock import today_b3`

---

## 2. Logic Chain

### Issue 1: AppConfig Load and `test_sandbox_config`
1. `AppConfig.load()` reads `config/universe.yaml` and maps `settings["_universe"]` to `universe["universe"]`.
2. As structured in both `config/universe.yaml` and `tests/e2e/config/universe.yaml`, the key `universe` contains a dictionary containing both `tickers` (a list) and `sectors` (a dict). E.g., `{'tickers': ['PETR4'], 'sectors': {'PETR4': 'energia'}}`.
3. Thus, `cfg.get("_universe")` returns the full dictionary instead of just the tickers list.
4. If a test queries `cfg.get("_universe")` expecting a list of tickers, it will receive the whole dictionary structure, resulting in an assertion failure (e.g. comparing the dictionary `{'tickers': ['PETR4'], 'sectors': {'PETR4': 'energia'}}` to list `["PETR4"]`).
5. To get only the tickers list, the test must query `cfg.get("_universe", "tickers")` or the `AppConfig.load()` method must be refactored to assign `settings["_universe"] = universe["universe"]["tickers"]`.

### Issue 2: Clock Mocking and `test_mock_b3_clock`
1. When multiple modules in the application package import a function directly using `from module import function` syntax (e.g. `from trading_bot.core.clock import today_b3`), python creates a direct binding in those importing modules' local namespaces to the original function object.
2. In `mock_b3_clock`, `monkeypatch.setattr("trading_bot.core.clock.today_b3", lambda: fixed_date)` is used. This replaces the `today_b3` attribute inside the `trading_bot.core.clock` module object.
3. However, it does not update the already-imported direct function references in other modules' local namespaces (e.g., `trading_bot.data.validator`, `trading_bot.data.cross_validation`).
4. Therefore, when those modules call `today_b3()`, they call the original unpatched function and get the actual system date (e.g., `2026-07-07`), causing clock mock assertions or validations to fail.
5. In `tests/e2e/test_infrastructure.py`, importing `clock` as a module `from trading_bot.core import clock` works because attributes on the module object are resolved dynamically. But if `test_infrastructure.py` itself or other files in the session import `today_b3` directly (or if other parts of the application run validator code during the tests), the unmocked date will leak.

---

## 3. Caveats
- Since this is a read-only investigation, no code modifications were applied. We did not run tests with modified code, but verified the behavior through codebase tracing.
- The `pytest tests/e2e/test_infrastructure.py` command executed in isolation passes because the test only verifies `clock.today_b3()`, but running the full suite exposes failures where `today_b3()` leaks the real system date inside modules like `validator.py` and `cross_validation.py`.

---

## 4. Conclusion & Proposed Fix Strategy

### Fix Strategy for Issue 1 (Sandbox Config):
1. **Option A (Recommended - Standardize AppConfig mapping):**
   If `_universe` is intended to store only the list of active tickers, modify `AppConfig.load()` in `trading_bot/core/config.py` (and the `sandbox_config` fixture in `tests/e2e/conftest.py`) to assign:
   ```python
   settings["_universe"] = universe["universe"]["tickers"]
   ```
   This standardizes `_universe` to be a `list[str]`. Then update the test assertions to match:
   ```python
   assert cfg.get("_universe") == ["PETR4"]
   ```
2. **Option B (Maintain Full Dictionary):**
   If `_universe` must contain both tickers and sectors, ensure the test suite is updated to consistently fetch nested keys, e.g.:
   ```python
   assert cfg.get("_universe", "tickers") == ["PETR4"]
   ```

### Fix Strategy for Issue 2 (Clock Mocking):
1. **Option A (Recommended - Refactor Imports):**
   Avoid `from trading_bot.core.clock import today_b3` in application modules. Instead, import the `clock` module and look up the attribute dynamically:
   ```python
   from trading_bot.core import clock
   # Use clock.today_b3() instead of today_b3()
   ```
   This ensures that monkeypatching `trading_bot.core.clock.today_b3` in `conftest.py` immediately affects all usages across the entire application codebase.
2. **Option B (Patch All Import Locations in Fixture):**
   If codebase imports cannot be changed, update the `mock_b3_clock` fixture in `tests/e2e/conftest.py` to explicitly patch the local binding of `today_b3` in every module where it was imported:
   ```python
   @pytest.fixture
   def mock_b3_clock(monkeypatch):
       fixed_date = date(2024, 6, 30)
       monkeypatch.setattr("trading_bot.core.clock.today_b3", lambda: fixed_date)
       monkeypatch.setattr("trading_bot.data.validator.today_b3", lambda: fixed_date)
       monkeypatch.setattr("trading_bot.data.cross_validation.today_b3", lambda: fixed_date)
       monkeypatch.setattr("trading_bot.data.ingestion.today_b3", lambda: fixed_date)
       monkeypatch.setattr("trading_bot.data.storage.today_b3", lambda: fixed_date)
       return fixed_date
   ```

---

## 5. Verification Method
1. Apply the chosen fix strategy (either refactoring imports or patching target modules).
2. Run the test command:
   ```bash
   pytest tests/e2e/test_infrastructure.py
   pytest tests/e2e/test_tier1_tier2.py
   pytest tests/e2e/test_tier3_tier4.py
   ```
3. Verify that all tests pass, and no warning logs or assertions indicate that the unmocked system date was returned (e.g. `2026-07-07`).

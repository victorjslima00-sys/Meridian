from unittest.mock import patch, MagicMock
from unittest.mock import patch, MagicMock
from trading_bot.core.scheduler import Scheduler

def test_scheduler_instantiates():
    s = Scheduler()
    assert s is not None

def test_scheduler_run_calls_scheduled_jobs(monkeypatch):
    called = []
    monkeypatch.setattr("schedule.run_pending", lambda: called.append(1))
    s = Scheduler()
    s.run_pending()  # deve chamar run_pending
    assert len(called) == 1

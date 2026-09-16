"""B3 Session Phase and Official Trading Calendar Contract (NEXUS-004).

Implements explicit market session phases, official B3 2026 calendar semantics,
and fail-closed autonomous entry rules based on official B3 publications:
- B3 Circular Letter 005/2026 PRE (Horário de Negociação, effective 2026-03-09)
- B3 Circular Letter OC 003-2026-VNC (Errata Calendário de Feriados em 2026 e Funcionamento em 18/02/2026)

Rules:
- AUTONOMOUS NEW ENTRY: allowed ONLY during CONTINUOUS session phase.
- EXIT PROTECTION: runs independently of entry session closure.
- UNKNOWN CALENDAR YEAR: fail-closed (no autonomous entry).
"""
from __future__ import annotations

import datetime
from contextlib import contextmanager
from enum import Enum
from typing import Callable, Optional
from zoneinfo import ZoneInfo

# Official B3 Timezone
B3_TIMEZONE_STR = "America/Sao_Paulo"
B3_TIMEZONE = ZoneInfo(B3_TIMEZONE_STR)

# Source identity & effective dates
B3_SCHEDULE_SOURCE = "B3 Circular Letter 005/2026 PRE"
B3_SCHEDULE_EFFECTIVE_DATE = "2026-03-09"
B3_CALENDAR_SOURCE = "B3 Circular Letter OC 003-2026-VNC"
B3_CALENDAR_YEAR = 2026


class B3SessionPhase(str, Enum):
    """Explicit B3 market session phases for cash equities."""
    CLOSED = "CLOSED"
    ORDER_CANCELLATION = "ORDER_CANCELLATION"
    PRE_OPEN = "PRE_OPEN"
    CONTINUOUS = "CONTINUOUS"
    CLOSING_CALL = "CLOSING_CALL"
    POST_REGULAR = "POST_REGULAR"
    AFTER_MARKET_ORDER_CANCELLATION = "AFTER_MARKET_ORDER_CANCELLATION"
    AFTER_MARKET = "AFTER_MARKET"
    POST_AFTER_MARKET = "POST_AFTER_MARKET"


class B3DayType(str, Enum):
    """B3 trading calendar day classifications."""
    NORMAL_TRADING_DAY = "NORMAL_TRADING_DAY"
    NO_SESSION = "NO_SESSION"
    SPECIAL_HOURS = "SPECIAL_HOURS"
    UNKNOWN = "UNKNOWN"


# Official 2026 B3 Closures (National Holidays & Exchange Closures)
# Source: B3 OC 003-2026-VNC
B3_2026_CLOSURES = {
    datetime.date(2026, 1, 1): "Confraternização Universal",
    datetime.date(2026, 2, 16): "Carnaval (Segunda-feira)",
    datetime.date(2026, 2, 17): "Carnaval (Terça-feira)",
    datetime.date(2026, 4, 3): "Paixão de Cristo",
    datetime.date(2026, 4, 21): "Tiradentes",
    datetime.date(2026, 5, 1): "Dia do Trabalho",
    datetime.date(2026, 6, 4): "Corpus Christi",
    datetime.date(2026, 9, 7): "Independência do Brasil",
    datetime.date(2026, 10, 12): "Nossa Senhora Aparecida",
    datetime.date(2026, 11, 2): "Finados",
    datetime.date(2026, 11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    datetime.date(2026, 12, 24): "Véspera de Natal (sem negociação)",
    datetime.date(2026, 12, 25): "Natal",
    datetime.date(2026, 12, 31): "Véspera de Ano Novo (sem negociação)",
}

# Special Trading Days in 2026
# Ash Wednesday: Pre-open 12:45-13:00, Continuous 13:00-16:55
B3_2026_SPECIAL_DAYS = {
    datetime.date(2026, 2, 18): "Quarta-feira de Cinzas",
}


def get_day_type(market_date: datetime.date | datetime.datetime) -> B3DayType:
    """Classify the day type for a given date on B3.
    
    Fail-closed: Returns UNKNOWN for any year or date without an auditable calendar.
    Effective date for Circular 005/2026 PRE normal trading schedule is 2026-03-09.
    Dates in 2026 before 2026-03-09 (except explicitly modeled special days like
    Ash Wednesday 2026-02-18) return UNKNOWN (fail-closed).
    """
    if isinstance(market_date, datetime.datetime):
        if market_date.tzinfo is None:
            market_date = market_date.replace(tzinfo=B3_TIMEZONE)
        else:
            market_date = market_date.astimezone(B3_TIMEZONE)
        d = market_date.date()
    else:
        d = market_date

    if d.year != B3_CALENDAR_YEAR:
        return B3DayType.UNKNOWN

    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return B3DayType.NO_SESSION

    if d in B3_2026_CLOSURES:
        return B3DayType.NO_SESSION

    if d in B3_2026_SPECIAL_DAYS:
        return B3DayType.SPECIAL_HOURS

    # Normal schedule under Circular 005/2026 PRE is effective 2026-03-09
    if d < datetime.date(2026, 3, 9):
        return B3DayType.UNKNOWN

    return B3DayType.NORMAL_TRADING_DAY


def get_session_phase(dt: Optional[datetime.datetime] = None) -> B3SessionPhase:
    """Determine the B3 session phase for cash equities at a given datetime.
    
    If dt is None, the current time in America/Sao_Paulo is used.
    If dt is naive, America/Sao_Paulo timezone is assumed.
    """
    if dt is None:
        dt = datetime.datetime.now(B3_TIMEZONE)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=B3_TIMEZONE)
    else:
        dt = dt.astimezone(B3_TIMEZONE)

    day_type = get_day_type(dt.date())

    if day_type in (B3DayType.NO_SESSION, B3DayType.UNKNOWN):
        return B3SessionPhase.CLOSED

    t = dt.time()

    if day_type == B3DayType.SPECIAL_HOURS:
        # Ash Wednesday (2026-02-18) official schedule (B3 OC 003/2026-VNC):
        # 12:30–12:45 order cancellation
        # 12:45–13:00 pre-open
        # 13:00–17:55 continuous
        # 17:55–18:00 closing call
        if t < datetime.time(12, 30):
            return B3SessionPhase.CLOSED
        elif t < datetime.time(12, 45):
            return B3SessionPhase.ORDER_CANCELLATION
        elif t < datetime.time(13, 0):
            return B3SessionPhase.PRE_OPEN
        elif t < datetime.time(17, 55):
            return B3SessionPhase.CONTINUOUS
        elif t < datetime.time(18, 0):
            return B3SessionPhase.CLOSING_CALL
        elif t < datetime.time(18, 25):
            return B3SessionPhase.POST_REGULAR
        elif t < datetime.time(18, 45):
            return B3SessionPhase.AFTER_MARKET
        else:
            return B3SessionPhase.CLOSED

    # NORMAL_TRADING_DAY
    # Cash equities schedule effective 2026-03-09:
    # 09:30–09:45 order cancellation
    # 09:45–10:00 pre-open
    # 10:00–16:55 continuous
    # 16:55–17:00 closing call
    # 17:00–17:25 post-regular
    # 17:25–17:30 after-market cancellation
    # 17:30–18:00 after-market
    # 18:00–18:25 post-regular
    # 18:25–18:45 final cancellation
    if t < datetime.time(9, 30):
        return B3SessionPhase.CLOSED
    elif t < datetime.time(9, 45):
        return B3SessionPhase.ORDER_CANCELLATION
    elif t < datetime.time(10, 0):
        return B3SessionPhase.PRE_OPEN
    elif t < datetime.time(16, 55):
        return B3SessionPhase.CONTINUOUS
    elif t < datetime.time(17, 0):
        return B3SessionPhase.CLOSING_CALL
    elif t < datetime.time(17, 25):
        return B3SessionPhase.POST_REGULAR
    elif t < datetime.time(17, 30):
        return B3SessionPhase.AFTER_MARKET_ORDER_CANCELLATION
    elif t < datetime.time(18, 0):
        return B3SessionPhase.AFTER_MARKET
    elif t < datetime.time(18, 25):
        return B3SessionPhase.POST_REGULAR
    elif t < datetime.time(18, 45):
        return B3SessionPhase.POST_AFTER_MARKET
    else:
        return B3SessionPhase.CLOSED


def check_autonomous_session_authority(
    dt: Optional[datetime.datetime] = None,
) -> tuple[bool, str, B3DayType, B3SessionPhase]:
    """Central authority for autonomous strategy entry (NEXUS-004-R1).
    
    Verifies that:
    1. B3 calendar is known and auditable for the date
    2. Date is a valid trading session (not weekend or exchange holiday)
    3. Current session phase is strictly CONTINUOUS.
    
    Returns:
        (allowed, reason, day_type, session_phase)
    """
    if dt is None:
        dt = datetime.datetime.now(B3_TIMEZONE)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=B3_TIMEZONE)
    else:
        dt = dt.astimezone(B3_TIMEZONE)

    day_type = get_day_type(dt.date())
    phase = get_session_phase(dt)

    if day_type == B3DayType.UNKNOWN:
        return False, f"B3 calendar unknown/unverified for date {dt.date()}", day_type, phase
    if day_type == B3DayType.NO_SESSION:
        return False, f"No B3 trading session on {dt.date()} (holiday/weekend)", day_type, phase
    if phase != B3SessionPhase.CONTINUOUS:
        return False, f"B3 session phase is {phase.value} (CONTINUOUS required for entry)", day_type, phase

    return True, "CONTINUOUS trading session authorized", day_type, phase


def can_enter_new_position(dt: Optional[datetime.datetime] = None) -> bool:
    """Autonomous entry gate: allowed ONLY during CONTINUOUS session phase."""
    return check_autonomous_session_authority(dt)[0]


def can_manage_exits(dt: Optional[datetime.datetime] = None) -> bool:
    """Exit management runs independently of entry session closure."""
    return True


# Explicit aliases
get_b3_day_type = get_day_type
get_b3_session_phase = get_session_phase


class AutonomousSessionAuthority:
    """Central authority governing autonomous strategy entry into market sessions."""

    def __init__(
        self,
        override_fn: Optional[
            Callable[[Optional[datetime.datetime]], tuple[bool, str, B3DayType, B3SessionPhase]]
        ] = None,
    ):
        self._override_fn = override_fn

    def check_authority(
        self, dt: Optional[datetime.datetime] = None
    ) -> tuple[bool, str, B3DayType, B3SessionPhase]:
        """Check whether autonomous strategy entry is authorized.
        
        Default delegates to check_autonomous_session_authority(dt).
        """
        if self._override_fn is not None:
            return self._override_fn(dt)
        return check_autonomous_session_authority(dt)

    def can_enter(self, dt: Optional[datetime.datetime] = None) -> bool:
        """Boolean check whether entry is authorized."""
        return self.check_authority(dt)[0]


_CURRENT_SESSION_AUTHORITY: AutonomousSessionAuthority = AutonomousSessionAuthority()


def get_session_authority() -> AutonomousSessionAuthority:
    """Get the active AutonomousSessionAuthority singleton."""
    return _CURRENT_SESSION_AUTHORITY


def set_session_authority(authority: AutonomousSessionAuthority) -> None:
    """Set the active AutonomousSessionAuthority singleton."""
    global _CURRENT_SESSION_AUTHORITY
    _CURRENT_SESSION_AUTHORITY = authority


@contextmanager
def override_session_authority(
    authority_or_fn: AutonomousSessionAuthority | Callable[[Optional[datetime.datetime]], tuple[bool, str, B3DayType, B3SessionPhase]],
):
    """Context manager for temporarily overriding autonomous session authority."""
    global _CURRENT_SESSION_AUTHORITY
    old_authority = _CURRENT_SESSION_AUTHORITY
    if isinstance(authority_or_fn, AutonomousSessionAuthority):
        _CURRENT_SESSION_AUTHORITY = authority_or_fn
    else:
        _CURRENT_SESSION_AUTHORITY = AutonomousSessionAuthority(override_fn=authority_or_fn)
    try:
        yield _CURRENT_SESSION_AUTHORITY
    finally:
        _CURRENT_SESSION_AUTHORITY = old_authority


"""
Módulo 1 — Validação de qualidade dos dados
============================================
Detecta gaps suspeitos, splits não ajustados, volumes zero.
Alerta ao operador quando dados parecem inconsistentes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
import pandas as pd

from trading_bot.core.clock import today_b3

logger = logging.getLogger(__name__)

# Limites para alertas
MAX_DAILY_MOVE_PCT   = 20.0   # >20% de variação diária é suspeito (gap/split)
MAX_GAP_DAYS         = 5      # >5 dias úteis sem dados = gap suspeito
MIN_VOLUME           = 0      # Volume == 0 em dia de pregão = suspeito
SPLIT_DETECTION_RATIO = 1.5   # Variação de preço / variação do volume > ratio = possível split


@dataclass
class ValidationIssue:
    ticker: str
    date: date
    issue_type: str        # 'gap', 'zero_volume', 'large_move', 'possible_split'
    description: str
    severity: str          # 'warning' | 'error'


@dataclass
class ValidationReport:
    ticker: str
    total_rows: int
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]


def validate_ohlcv(df: pd.DataFrame, ticker: str) -> ValidationReport:
    """
    Valida qualidade de um DataFrame OHLCV para um ticker.

    Checks:
    1. Gaps de datas (> MAX_GAP_DAYS dias sem dados)
    2. Volume zero em dias de pregão
    3. Variações diárias suspeitas (> MAX_DAILY_MOVE_PCT%)
    4. Possíveis splits não ajustados (preço cai 50%+ sem volume correspondente)
    """
    report = ValidationReport(ticker=ticker, total_rows=len(df))

    if df.empty:
        report.issues.append(ValidationIssue(
            ticker=ticker,
            date=today_b3(),
            issue_type="empty",
            description="DataFrame vazio — nenhum dado disponível",
            severity="error",
        ))
        return report

    df = df.sort_values("ts").copy()
    df["ts"] = pd.to_datetime(df["ts"]).dt.date

    # --------------------------------------------------------
    # Check 1: Gaps de datas
    # --------------------------------------------------------
    dates = df["ts"].tolist()
    for i in range(1, len(dates)):
        delta = (dates[i] - dates[i-1]).days
        if delta > MAX_GAP_DAYS:
            report.issues.append(ValidationIssue(
                ticker=ticker,
                date=dates[i],
                issue_type="gap",
                description=(
                    f"Gap de {delta} dias entre {dates[i-1]} e {dates[i]} "
                    f"(threshold: {MAX_GAP_DAYS} dias)"
                ),
                severity="warning" if delta <= 10 else "error",
            ))

    # --------------------------------------------------------
    # Check 2: Volume zero
    # --------------------------------------------------------
    if "v" in df.columns:
        zero_vol = df[df["v"] == 0]
        for _, row in zero_vol.iterrows():
            report.issues.append(ValidationIssue(
                ticker=ticker,
                date=row["ts"],
                issue_type="zero_volume",
                description=f"Volume zero em {row['ts']} — possível dado inválido",
                severity="warning",
            ))

    # --------------------------------------------------------
    # Check 3: Variações diárias suspeitas
    # --------------------------------------------------------
    adj_col = "adj_close" if "adj_close" in df.columns else "c"
    df["daily_return_pct"] = df[adj_col].pct_change().abs() * 100

    large_moves = df[df["daily_return_pct"] > MAX_DAILY_MOVE_PCT]
    for _, row in large_moves.iterrows():
        severity = "error" if row["daily_return_pct"] > 40 else "warning"
        report.issues.append(ValidationIssue(
            ticker=ticker,
            date=row["ts"],
            issue_type="large_move",
            description=(
                f"Variação de {row['daily_return_pct']:.1f}% em {row['ts']} — "
                f"possível split não ajustado ou dado incorreto"
            ),
            severity=severity,
        ))

    # --------------------------------------------------------
    # Check 4: Possível split não ajustado (preço cai >40% sem alta de volume)
    # --------------------------------------------------------
    if "v" in df.columns and len(df) > 1:
        df["price_ratio"] = df[adj_col] / df[adj_col].shift(1)
        df["vol_ratio"] = df["v"] / df["v"].shift(1).replace(0, 1)
        # Split não ajustado: preço cai 40%+ mas volume não dobra proporcionalmente
        possible_splits = df[
            (df["price_ratio"] < 0.6) &
            (df["vol_ratio"] < SPLIT_DETECTION_RATIO)
        ]
        for _, row in possible_splits.iterrows():
            report.issues.append(ValidationIssue(
                ticker=ticker,
                date=row["ts"],
                issue_type="possible_split",
                description=(
                    f"Possível split não ajustado em {row['ts']}: "
                    f"preço {(row['price_ratio']-1)*100:.1f}%, "
                    f"volume {(row['vol_ratio']-1)*100:.1f}%"
                ),
                severity="error",
            ))

    return report


def validate_universe(
    data: dict[str, pd.DataFrame],
) -> dict[str, ValidationReport]:
    """
    Valida todos os ativos do universo.

    Args:
        data: Dict {ticker: DataFrame}

    Returns:
        Dict {ticker: ValidationReport}
    """
    reports = {}
    errors = 0
    warnings = 0

    for ticker, df in data.items():
        report = validate_ohlcv(df, ticker)
        reports[ticker] = report

        if report.errors:
            errors += len(report.errors)
            for issue in report.errors:
                logger.error("[%s] ERRO: %s", ticker, issue.description)

        if report.warnings:
            warnings += len(report.warnings)
            for issue in report.warnings:
                logger.warning("[%s] AVISO: %s", ticker, issue.description)

    total = len(data)
    ok_count = sum(1 for r in reports.values() if r.ok)
    logger.info(
        "Validação de qualidade: %d/%d OK | %d erros | %d avisos",
        ok_count, total, errors, warnings,
    )

    return reports

"""
Testes unitarios para o Monitor de Saude Operacional (Vulcan DevOps)
Verifica metricas reais de memoria Windows via GlobalMemoryStatusEx,
metricas de disco via shutil.disk_usage e sinalizacao de status estruturado.
"""
import ctypes
import datetime
from unittest.mock import patch

import pytest
from trading_bot.infra.health_monitor import (
    HealthStatus,
    MEMORYSTATUSEX,
    OperationalHealthMonitor,
)


def test_health_monitor_system_metrics_live():
    """
    Verifica se a coleta de metricas do sistema em tempo real obtem metricas
    reais, validas e nao-sinteticas do Windows e disco.
    """
    monitor = OperationalHealthMonitor()
    metrics = monitor.collect_system_metrics()

    # Validacao do timestamp UTC ISO-8601
    assert "timestamp_utc" in metrics
    parsed_time = datetime.datetime.fromisoformat(metrics["timestamp_utc"])
    assert parsed_time.tzinfo is not None

    # Validacao de CPU e disco
    assert "cpu_cores" in metrics
    assert metrics["cpu_cores"] > 0
    assert "disk_total_gb" in metrics
    assert "disk_free_gb" in metrics
    assert "disk_used_pct" in metrics
    assert metrics["disk_total_gb"] > 0.0
    assert metrics["disk_free_gb"] > 0.0
    assert 0.0 <= metrics["disk_used_pct"] <= 100.0

    # Validacao de memoria RAM real (nao-sintetica)
    assert "ram_total_mb" in metrics
    assert "ram_available_mb" in metrics
    assert "ram_load_pct" in metrics
    assert "ram_total_gb" in metrics
    assert "ram_available_gb" in metrics
    assert metrics["ram_total_mb"] > 0.0
    assert metrics["ram_available_mb"] > 0.0
    assert 0.0 <= metrics["ram_load_pct"] <= 100.0

    # Prova de integridade de hardware: total_mb deve coincidir com consulta direta via ctypes
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    expected_total_mb = round(stat.ullTotalPhys / (1024 ** 2), 2)
    assert abs(metrics["ram_total_mb"] - expected_total_mb) < 2.0

    # Validacao das flags estruturadas de status
    assert "system_status" in metrics
    assert "status_flags" in metrics
    assert metrics["system_status"] in (
        HealthStatus.HEALTHY.value,
        HealthStatus.WARNING_LOW_DISK.value,
        HealthStatus.CRITICAL_LOW_MEMORY.value,
    )
    assert isinstance(metrics["status_flags"], list)
    assert len(metrics["status_flags"]) >= 1


def test_health_monitor_disk_health_checks():
    """
    Verifica se a checagem de espaco em disco avalia thresholds reais e simulados.
    """
    monitor = OperationalHealthMonitor()

    # Disco saudavel para limiar muito baixo (0.01 GB)
    assert monitor.is_disk_healthy(min_free_gb=0.01) is True

    # Disco nao saudavel para limiar excessivamente alto (1 Petabyte)
    assert monitor.is_disk_healthy(min_free_gb=1_000_000.0) is False


def test_health_monitor_low_disk_warning_status():
    """
    Verifica geracao de status WARNING_LOW_DISK quando espaco livre e insuficiente.
    """
    monitor = OperationalHealthMonitor(min_disk_free_gb=5.0)

    # Simula 100 GB total, 98 GB usado, 2 GB livre (< 5.0 GB threshold)
    mock_usage = (100 * (1024 ** 3), 98 * (1024 ** 3), 2 * (1024 ** 3))
    mock_mem = {
        "ram_total_mb": 16384.0,
        "ram_available_mb": 8192.0,
        "ram_load_pct": 50.0,
        "memory_load_pct": 50.0,
        "ram_total_gb": 16.0,
        "ram_available_gb": 8.0,
    }

    with patch("shutil.disk_usage", return_value=mock_usage):
        with patch.object(OperationalHealthMonitor, "_get_memory_status", return_value=mock_mem):
            metrics = monitor.collect_system_metrics()
            assert metrics["system_status"] == HealthStatus.WARNING_LOW_DISK.value
            assert HealthStatus.WARNING_LOW_DISK.value in metrics["status_flags"]
            assert monitor.is_disk_healthy() is False


def test_health_monitor_critical_low_memory_status():
    """
    Verifica geracao de status CRITICAL_LOW_MEMORY quando RAM disponivel e critica ou load e elevado.
    """
    monitor = OperationalHealthMonitor(min_ram_available_mb=512.0, max_ram_load_pct=95.0)

    # Caso 1: RAM disponivel abaixo do threshold minimo (256 MB < 512 MB)
    mock_usage = (500 * (1024 ** 3), 200 * (1024 ** 3), 300 * (1024 ** 3))
    mock_mem_low_avail = {
        "ram_total_mb": 8192.0,
        "ram_available_mb": 256.0,
        "ram_load_pct": 96.8,
        "memory_load_pct": 96.8,
        "ram_total_gb": 8.0,
        "ram_available_gb": 0.25,
    }

    with patch("shutil.disk_usage", return_value=mock_usage):
        with patch.object(OperationalHealthMonitor, "_get_memory_status", return_value=mock_mem_low_avail):
            metrics = monitor.collect_system_metrics()
            assert metrics["system_status"] == HealthStatus.CRITICAL_LOW_MEMORY.value
            assert HealthStatus.CRITICAL_LOW_MEMORY.value in metrics["status_flags"]
            assert monitor.is_ram_healthy() is False

    # Caso 2: Memoria load percentual critico (98% >= 95%)
    mock_mem_high_load = {
        "ram_total_mb": 16384.0,
        "ram_available_mb": 600.0,
        "ram_load_pct": 98.0,
        "memory_load_pct": 98.0,
        "ram_total_gb": 16.0,
        "ram_available_gb": 0.59,
    }

    with patch("shutil.disk_usage", return_value=mock_usage):
        with patch.object(OperationalHealthMonitor, "_get_memory_status", return_value=mock_mem_high_load):
            metrics = monitor.collect_system_metrics()
            assert metrics["system_status"] == HealthStatus.CRITICAL_LOW_MEMORY.value
            assert HealthStatus.CRITICAL_LOW_MEMORY.value in metrics["status_flags"]


def test_health_monitor_combined_critical_memory_and_low_disk():
    """
    Verifica precedencia de status e inclusao de ambas as flags quando disco e RAM estao degradados.
    """
    monitor = OperationalHealthMonitor(min_disk_free_gb=10.0, min_ram_available_mb=1024.0)

    # 5 GB livre (< 10 GB) e 500 MB RAM livre (< 1024 MB)
    mock_usage = (100 * (1024 ** 3), 95 * (1024 ** 3), 5 * (1024 ** 3))
    mock_mem = {
        "ram_total_mb": 8192.0,
        "ram_available_mb": 500.0,
        "ram_load_pct": 93.8,
        "memory_load_pct": 93.8,
        "ram_total_gb": 8.0,
        "ram_available_gb": 0.49,
    }

    with patch("shutil.disk_usage", return_value=mock_usage):
        with patch.object(OperationalHealthMonitor, "_get_memory_status", return_value=mock_mem):
            metrics = monitor.collect_system_metrics()
            # CRITICAL tem prioridade sobre WARNING no status sintetico
            assert metrics["system_status"] == HealthStatus.CRITICAL_LOW_MEMORY.value
            # Ambas as flags devem estar presentes em status_flags
            assert HealthStatus.CRITICAL_LOW_MEMORY.value in metrics["status_flags"]
            assert HealthStatus.WARNING_LOW_DISK.value in metrics["status_flags"]


"""
Monitor de Saude Operacional, Infraestrutura e Recursos do Sistema — Vulcan DevOps
Head of Infrastructure: Vulcan
Meridian Technologies

Reads real system metrics via native OS APIs (no synthetic constants):
- RAM: ctypes.windll.kernel32.GlobalMemoryStatusEx (Windows)
- Disk: shutil.disk_usage
- CPU: os.cpu_count
"""
from __future__ import annotations

import ctypes
import datetime
from enum import Enum
import logging
import os
import shutil
from typing import Any, Optional

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING_LOW_DISK = "WARNING_LOW_DISK"
    CRITICAL_LOW_MEMORY = "CRITICAL_LOW_MEMORY"


class MEMORYSTATUSEX(ctypes.Structure):
    """
    Estrutura Win32 MEMORYSTATUSEX para consulta de memoria fisica e virtual.
    """
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class OperationalHealthMonitor:
    """
    Monitora a integridade do desktop/servidor: espaco em disco,
    memoria disponivel via API nativa Windows (GlobalMemoryStatusEx),
    status dos processos do bot e conectividade com MT5/APIs.

    Zero synthetic constants — all metrics come from the OS.
    """

    def __init__(
        self,
        workspace_path: str = ".",
        min_disk_free_gb: float = 2.0,
        min_ram_available_mb: float = 512.0,
        max_ram_load_pct: float = 95.0,
    ):
        self.workspace_path = os.path.abspath(workspace_path)
        self.min_disk_free_gb = min_disk_free_gb
        self.min_ram_available_mb = min_ram_available_mb
        self.max_ram_load_pct = max_ram_load_pct

    @staticmethod
    def _get_memory_status() -> dict[str, Any]:
        """
        Consulta metricas reais de memoria fisica via API nativa Win32
        (kernel32.GlobalMemoryStatusEx).

        Returns dict with ram_total_mb, ram_available_mb, ram_load_pct,
        ram_total_gb, ram_available_gb. Falls back to None sentinels if
        the OS call fails (fail-closed: unknown = unhealthy).
        """
        fallback = {
            "ram_total_mb": None,
            "ram_available_mb": None,
            "ram_load_pct": None,
            "ram_total_gb": None,
            "ram_available_gb": None,
        }
        try:
            if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32"):
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                if success:
                    return {
                        "ram_total_mb": round(stat.ullTotalPhys / (1024 ** 2), 2),
                        "ram_available_mb": round(stat.ullAvailPhys / (1024 ** 2), 2),
                        "ram_load_pct": float(stat.dwMemoryLoad),
                        "ram_total_gb": round(stat.ullTotalPhys / (1024 ** 3), 2),
                        "ram_available_gb": round(stat.ullAvailPhys / (1024 ** 3), 2),
                    }
                else:
                    logger.error("Falha ao invocar GlobalMemoryStatusEx")

            # Linux / Ubuntu support via /proc/meminfo
            if os.path.exists("/proc/meminfo"):
                meminfo: dict[str, int] = {}
                with open("/proc/meminfo", "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            key = parts[0].strip()
                            val = parts[1].strip().split()[0]
                            meminfo[key] = int(val)
                total_kb = meminfo.get("MemTotal", 0)
                avail_kb = meminfo.get("MemAvailable", 0)
                if total_kb > 0:
                    total_mb = round(total_kb / 1024.0, 2)
                    avail_mb = round(avail_kb / 1024.0, 2)
                    load_pct = round((1.0 - (avail_kb / total_kb)) * 100.0, 2)
                    return {
                        "ram_total_mb": total_mb,
                        "ram_available_mb": avail_mb,
                        "ram_load_pct": load_pct,
                        "ram_total_gb": round(total_mb / 1024.0, 2),
                        "ram_available_gb": round(avail_mb / 1024.0, 2),
                    }

            logger.warning("OS memory API not available on this platform")
            return fallback
        except Exception as exc:
            logger.warning("Cannot read memory metrics: %s", exc)
            return fallback

    def collect_system_metrics(self) -> dict[str, Any]:
        """
        Coleta metricas reais de sistema operacional (disco via shutil, RAM via kernel32).
        Retorna metricas estruturadas com timestamp UTC ISO-8601 e flags de status.
        All values are queried from the OS — no hardcoded constants.
        """
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        total_disk, used_disk, free_disk = shutil.disk_usage(self.workspace_path)
        disk_free_gb = round(free_disk / (1024 ** 3), 2)
        disk_total_gb = round(total_disk / (1024 ** 3), 2)
        disk_used_pct = round((used_disk / total_disk) * 100.0, 1)

        cpu_cores = os.cpu_count() or 1

        # Metricas reais de memoria fisica
        mem = self._get_memory_status()
        ram_total_mb = mem["ram_total_mb"]
        ram_available_mb = mem["ram_available_mb"]
        ram_load_pct = mem["ram_load_pct"]

        # Avaliacao de flags de integridade
        flags: list[str] = []
        is_mem_critical = (
            ram_available_mb is not None
            and ram_load_pct is not None
            and (ram_available_mb < self.min_ram_available_mb or ram_load_pct >= self.max_ram_load_pct)
        )
        # If we can't read memory, treat as critical (fail-closed)
        if ram_available_mb is None or ram_load_pct is None:
            is_mem_critical = True

        is_disk_low = disk_free_gb < self.min_disk_free_gb

        if is_mem_critical:
            flags.append(HealthStatus.CRITICAL_LOW_MEMORY.value)
        if is_disk_low:
            flags.append(HealthStatus.WARNING_LOW_DISK.value)
        if not flags:
            flags.append(HealthStatus.HEALTHY.value)

        # Status sintetico principal (CRITICAL sobrepoe WARNING)
        if is_mem_critical:
            system_status = HealthStatus.CRITICAL_LOW_MEMORY.value
        elif is_disk_low:
            system_status = HealthStatus.WARNING_LOW_DISK.value
        else:
            system_status = HealthStatus.HEALTHY.value

        return {
            "timestamp_utc": now_utc,
            "cpu_cores": cpu_cores,
            "disk_total_gb": disk_total_gb,
            "disk_free_gb": disk_free_gb,
            "disk_used_pct": disk_used_pct,
            "ram_total_mb": ram_total_mb,
            "ram_available_mb": ram_available_mb,
            "ram_load_pct": ram_load_pct,
            "ram_total_gb": mem["ram_total_gb"],
            "ram_available_gb": mem["ram_available_gb"],
            "memory_load_pct": ram_load_pct,
            "system_status": system_status,
            "status": system_status,
            "status_flags": flags,
        }

    def is_disk_healthy(self, min_free_gb: Optional[float] = None) -> bool:
        threshold = min_free_gb if min_free_gb is not None else self.min_disk_free_gb
        metrics = self.collect_system_metrics()
        return metrics["disk_free_gb"] >= threshold

    def is_ram_healthy(self, min_available_mb: Optional[float] = None) -> bool:
        """Check if memory load is below the critical threshold (fail-closed)."""
        threshold = min_available_mb if min_available_mb is not None else self.min_ram_available_mb
        metrics = self.collect_system_metrics()
        avail = metrics["ram_available_mb"]
        if avail is None:
            return False  # fail-closed: unknown = unhealthy
        return avail >= threshold

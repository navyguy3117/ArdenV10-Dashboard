"""
metrics.py - System metrics collection using psutil
Collects CPU, RAM, disk, and network I/O stats
"""
import psutil
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import logging

logger = logging.getLogger("command_center.metrics")


@dataclass
class DiskInfo:
    device: str
    mountpoint: str
    total: int
    used: int
    free: int
    percent: float


@dataclass
class NetworkInfo:
    bytes_sent_per_sec: float
    bytes_recv_per_sec: float
    bytes_sent_total: int
    bytes_recv_total: int


@dataclass
class SystemMetrics:
    cpu_percent: float
    cpu_per_core: List[float]
    memory_used: int
    memory_total: int
    memory_percent: float
    memory_available: int
    swap_used: int
    swap_total: int
    swap_percent: float
    disks: List[DiskInfo]
    network: NetworkInfo
    uptime_s: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "cpu_percent":     round(self.cpu_percent, 1),
            "cpu_per_core":    [round(c, 1) for c in self.cpu_per_core],
            "memory_used":     self.memory_used,
            "memory_total":    self.memory_total,
            "memory_percent":  round(self.memory_percent, 1),
            "memory_used_gb":  round(self.memory_used  / (1024 ** 3), 2),
            "memory_total_gb": round(self.memory_total / (1024 ** 3), 2),
            "memory_available": self.memory_available,
            "swap_used":       self.swap_used,
            "swap_total":      self.swap_total,
            "swap_percent":    round(self.swap_percent, 1),
            "disk": [
                {
                    "device":     d.device,
                    "mountpoint": d.mountpoint,
                    "total":      d.total,
                    "used":       d.used,
                    "free":       d.free,
                    "percent":    round(d.percent, 1),
                }
                for d in self.disks
            ],
            "network": {
                # short aliases used by the frontend
                "bytes_sent_ps":      round(self.network.bytes_sent_per_sec, 0),
                "bytes_recv_ps":      round(self.network.bytes_recv_per_sec, 0),
                # long-form names kept for any other consumers
                "bytes_sent_per_sec": round(self.network.bytes_sent_per_sec, 0),
                "bytes_recv_per_sec": round(self.network.bytes_recv_per_sec, 0),
                "bytes_sent_total":   self.network.bytes_sent_total,
                "bytes_recv_total":   self.network.bytes_recv_total,
            },
            "uptime_s":  round(self.uptime_s, 0),
            "timestamp": self.timestamp,
        }

    def status_color(self) -> str:
        """Returns overall status color based on metrics."""
        max_metric = max(self.cpu_percent, self.memory_percent)
        if max_metric >= 85:
            return "red"
        elif max_metric >= 60:
            return "amber"
        return "green"


class MetricsCollector:
    def __init__(self):
        self._last_net_io = psutil.net_io_counters()
        self._last_net_time = time.time()
        # Warm up CPU measurement
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    def collect(self) -> SystemMetrics:
        try:
            # CPU - non-blocking (uses interval from last call)
            cpu_overall = psutil.cpu_percent(interval=None)
            try:
                cpu_cores = psutil.cpu_percent(percpu=True, interval=None)
            except Exception:
                cpu_cores = [cpu_overall]

            # Memory
            mem = psutil.virtual_memory()
            try:
                swap = psutil.swap_memory()
                swap_used = swap.used
                swap_total = swap.total
                swap_percent = swap.percent
            except Exception:
                swap_used = swap_total = 0
                swap_percent = 0.0

            # Disks
            disks = []
            try:
                for part in psutil.disk_partitions(all=False):
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        disks.append(DiskInfo(
                            device=part.device,
                            mountpoint=part.mountpoint,
                            total=usage.total,
                            used=usage.used,
                            free=usage.free,
                            percent=usage.percent,
                        ))
                    except PermissionError:
                        continue
                    except Exception:
                        continue
            except Exception:
                pass

            # Network I/O delta
            try:
                now_net = psutil.net_io_counters()
                now_time = time.time()
                elapsed = max(now_time - self._last_net_time, 0.001)
                sent_per_sec = (now_net.bytes_sent - self._last_net_io.bytes_sent) / elapsed
                recv_per_sec = (now_net.bytes_recv - self._last_net_io.bytes_recv) / elapsed
                self._last_net_io = now_net
                self._last_net_time = now_time
                network = NetworkInfo(
                    bytes_sent_per_sec=max(0, sent_per_sec),
                    bytes_recv_per_sec=max(0, recv_per_sec),
                    bytes_sent_total=now_net.bytes_sent,
                    bytes_recv_total=now_net.bytes_recv,
                )
            except Exception:
                network = NetworkInfo(0, 0, 0, 0)

            try:
                uptime_s = time.time() - psutil.boot_time()
            except Exception:
                uptime_s = 0.0

            return SystemMetrics(
                cpu_percent=cpu_overall,
                cpu_per_core=cpu_cores,
                memory_used=mem.used,
                memory_total=mem.total,
                memory_percent=mem.percent,
                memory_available=mem.available,
                swap_used=swap_used,
                swap_total=swap_total,
                swap_percent=swap_percent,
                disks=disks,
                network=network,
                uptime_s=uptime_s,
            )

        except Exception as e:
            logger.error(f"Metrics collection error: {e}")
            # Return minimal fallback metrics
            return SystemMetrics(
                cpu_percent=0.0,
                cpu_per_core=[0.0],
                memory_used=0,
                memory_total=1,
                memory_percent=0.0,
                memory_available=1,
                swap_used=0,
                swap_total=0,
                swap_percent=0.0,
                disks=[],
                network=NetworkInfo(0, 0, 0, 0),
            )

    @staticmethod
    def format_bytes(b: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} PB"

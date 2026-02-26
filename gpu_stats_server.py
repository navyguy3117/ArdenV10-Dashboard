#!/usr/bin/env python3
"""
gpu_stats_server.py — Tiny GPU metrics HTTP server.
Zero external dependencies (stdlib + nvidia-smi).

Run on any NVIDIA machine:
    python3 gpu_stats_server.py          # default port 18765
    python3 gpu_stats_server.py 18765    # explicit port

Endpoints:
    GET /gpu   → JSON with GPU stats
    GET /       → same

Systemd one-liner (optional — run as a service):
    sudo nano /etc/systemd/system/gpu-stats.service
    --
    [Unit]
    Description=GPU Stats HTTP Server
    After=network.target

    [Service]
    ExecStart=/usr/bin/python3 /opt/gpu_stats_server.py
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
    --
    sudo systemctl enable --now gpu-stats
"""
import subprocess
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18765


def get_gpu_stats() -> dict:
    """Query nvidia-smi for GPU stats. Returns available=False on failure."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,"
                "memory.used,memory.total,power.draw,fan.speed",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            p = [x.strip() for x in result.stdout.strip().split(",")]
            mem_used  = float(p[3])
            mem_total = float(p[4])
            mem_pct   = round(mem_used / mem_total * 100, 1) if mem_total > 0 else 0

            def _f(val, fallback=None):
                try:
                    v = val.strip()
                    if v in ("[N/A]", "N/A", ""):
                        return fallback
                    return float(v)
                except (ValueError, AttributeError):
                    return fallback

            return {
                "available":    True,
                "name":         p[0],
                "temp_c":       _f(p[1]),
                "util_pct":     _f(p[2]),
                "mem_used_mb":  mem_used,
                "mem_total_mb": mem_total,
                "mem_pct":      mem_pct,
                "power_w":      _f(p[5]) if len(p) > 5 else None,
                "fan_pct":      _f(p[6]) if len(p) > 6 else None,
            }
    except FileNotFoundError:
        return {"available": False, "error": "nvidia-smi not found"}
    except Exception as e:
        return {"available": False, "error": str(e)}
    return {"available": False}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") in ("", "/gpu"):
            body = json.dumps(get_gpu_stats()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silent — no console spam


if __name__ == "__main__":
    print(f"[gpu-stats] Listening on 0.0.0.0:{PORT}  →  GET /gpu")
    try:
        HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[gpu-stats] Stopped.")

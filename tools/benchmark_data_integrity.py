"""Reproducible storage/backup benchmarks for the data-integrity closure.

Run from the repository root:

    .\.venv\Scripts\python.exe tools\benchmark_data_integrity.py

The fixture contains synthetic task records only. It never reads a real profile.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litebrowser.core import prefs, storage_health
from litebrowser.services import backup_service, encrypted_backup_service, life_service


def _tasks(count: int) -> list[dict]:
    now = int(time.time())
    return [
        {
            "id": uuid.uuid4().hex,
            "title": f"Benchmark task {index}",
            "bucket": "personal",
            "completed": index % 3 == 0,
            "due_at": 0,
            "workspace_id": "default",
            "created_at": now,
            "updated_at": now,
            "sync_state": "local",
            "archived": False,
        }
        for index in range(count)
    ]


def _measure(label: str, function):
    started = time.perf_counter()
    value = function()
    return {"operation": label, "seconds": round(time.perf_counter() - started, 4), "ok": bool(value)}


def run(count: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="mei-bench-") as temp:
        base = prefs.ensure_profile_layout(os.path.join(temp, "profile"))
        destination = os.path.join(temp, "backups")
        life_service.save_tasks(base, _tasks(count))
        rows = []
        rows.append(_measure("storage_health_scan", lambda: storage_health.health_summary(base)["healthy"]))
        plain_result = {}

        def make_plain():
            plain_result["value"] = backup_service.create_backup(
                base, destination=destination
            )
            return plain_result["value"].ok

        rows.append(_measure("verified_backup", make_plain))
        plain = plain_result["value"]
        encrypted_result = {}

        def make_encrypted():
            encrypted_result["value"] = encrypted_backup_service.create_encrypted_backup(
                base, "benchmark-only-password", destination=destination
            )
            return encrypted_result["value"].ok

        rows.append(_measure("encrypted_backup", make_encrypted))
        encrypted = encrypted_result["value"]
        rows.append(
            _measure(
                "encrypted_verify",
                lambda: encrypted_backup_service.verify_encrypted(
                    encrypted.path, "benchmark-only-password"
                )["ok"],
            )
        )
        return {"tasks": count, "operations": rows, "plain_bytes": os.path.getsize(plain.path) if plain.ok else 0}


if __name__ == "__main__":
    print(json.dumps([run(count) for count in (100, 2_000, 10_000)], indent=2))

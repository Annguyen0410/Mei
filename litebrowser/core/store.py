"""Versioned JSON stores: locking, atomic writes and upgrades in one place.

Every service used to re-implement "read the file, normalise it, write it back",
and each store carried its own idea of versioning (or none). Changing a store's
shape therefore had no upgrade path, and a newer build reading an older profile
silently reinterpreted the data.

A store is described once:

    PLAN_STORE = StoreSpec(
        name="personal_plan.json",
        version=PLAN_VERSION,
        default=_default_plan,
    )

and then read/written through :func:`read_store` / :func:`write_store`, which:

* take the per-profile lock (the profile has one writer, always);
* write atomically via ``storage_utils.write_json``;
* stamp the schema version on every write;
* upgrade older payloads through the stepwise registry in ``core/migrations.py``
  and persist the upgraded payload exactly once;
* refuse to rewrite a payload written by a *newer* build (no silent downgrade).
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from litebrowser.core import migration_journal, migrations, storage_health
from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import write_json

_log = get_logger("store")

VERSION_KEY = "version"
LEGACY_VERSION = 1


class StoreWriteError(OSError):
    """A store cannot be safely rewritten by this build."""


class StoreReadError(OSError):
    """A store exists but cannot be interpreted; its bytes were preserved.

    Callers must not substitute the store's default payload.  The original file
    is left in place and a quarantine copy is recorded for recovery.
    """

    def __init__(self, message: str, *, status: str = "", quarantine: dict | None = None):
        super().__init__(message)
        self.status = status
        self.quarantine = dict(quarantine or {})


@dataclass(frozen=True)
class StoreSpec:
    name: str
    version: int
    default: Callable[[], Any]
    subdir: str = ""
    migrate: Callable[[dict, int], dict] | None = field(default=None, compare=False)


def store_path(base_dir: str, spec: StoreSpec) -> str:
    directory = os.path.join(base_dir, spec.subdir) if spec.subdir else base_dir
    return os.path.join(directory, spec.name)


def stored_version(raw: Any) -> int:
    """Version of a payload on disk; missing/!garbage means the legacy version."""
    if not isinstance(raw, dict):
        return LEGACY_VERSION
    try:
        return int(raw.get(VERSION_KEY, LEGACY_VERSION) or LEGACY_VERSION)
    except (TypeError, ValueError, OverflowError):
        return LEGACY_VERSION


def _upgrade(raw: Any, spec: StoreSpec, path: str) -> tuple[Any, bool]:
    """Return (payload, persist?) for a payload read from ``path``."""
    if not isinstance(raw, dict):
        return spec.default(), False
    version = stored_version(raw)
    if version > spec.version:
        # A newer build wrote this profile. Leave it alone: rewriting would drop
        # fields this build does not know about.
        _log.warning(
            "%s is version %s but this build understands %s — leaving it untouched",
            path,
            version,
            spec.version,
        )
        return raw, False
    if version == spec.version:
        return raw, False
    try:
        if spec.migrate is not None:
            upgraded = spec.migrate(dict(raw), version)
        else:
            upgraded = migrations.migrate(spec.name, dict(raw), version, spec.version)
    except migrations.MissingMigration as exc:
        _log.warning("cannot upgrade %s: %s", path, exc)
        return raw, False
    if not isinstance(upgraded, dict):
        return raw, False
    upgraded[VERSION_KEY] = spec.version
    _log.info("upgraded %s from version %s to %s", path, version, spec.version)
    return upgraded, True


def _validate_payload(spec: StoreSpec, payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("migrated payload is not an object")
    if stored_version(payload) != spec.version:
        raise ValueError("migrated payload does not carry the target version")
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def _migrate_with_journal(base_dir: str, spec: StoreSpec, path: str, raw: dict, upgraded: dict) -> bool:
    """Persist a migrated payload through an explicit, recoverable sequence.

    Returns True when the replacement landed.  Any failure returns False and
    leaves the original file untouched; the journal and snapshot explain why.
    """
    try:
        entry = migration_journal.begin(
            base_dir,
            store_name=spec.name,
            source_version=stored_version(raw),
            target_version=spec.version,
        )
    except Exception as exc:
        _log.warning("not migrating %s: journal unavailable (%s)", spec.name, exc)
        return False
    journal_id = str(entry["id"])
    try:
        snapshot, input_sha = migration_journal.create_snapshot(
            base_dir, path, spec.name, stored_version(raw)
        )
        migration_journal.mark_backup_created(base_dir, journal_id, snapshot, input_sha)
        migration_journal.mark_applying(base_dir, journal_id)
        _validate_payload(spec, upgraded)
        migration_journal.mark_validating(base_dir, journal_id)
        write_json(path, upgraded)
        output_sha = hashlib.sha256(
            json.dumps(upgraded, ensure_ascii=False, indent=2).encode("utf-8")
        ).hexdigest()
        migration_journal.mark_committed(base_dir, journal_id, output_sha)
        return True
    except Exception as exc:
        try:
            migration_journal.mark_failed(
                base_dir, journal_id, str(exc), recovery_required=True
            )
        except Exception as journal_exc:
            _log.warning("migration journal update failed: %s", journal_exc)
        _log.warning("migration of %s was stopped safely: %s", spec.name, exc)
        return False


def read_store(base_dir: str, spec: StoreSpec) -> Any:
    """Read a store, upgrading and persisting an older payload once.

    Missing means a genuine first run and returns the default.  A file that
    exists but cannot be parsed is *not* treated as empty: a quarantine copy is
    recorded and :class:`StoreReadError` is raised, so no later write can erase
    recoverable bytes without an explicit recovery decision.
    """
    path = store_path(base_dir, spec)
    if not os.path.isfile(path):
        return spec.default()
    with profile_locked(base_dir):
        result = storage_health.read_json_checked(path, dict)
        if not result.ok:
            try:
                record = storage_health.quarantine_file(
                    base_dir,
                    path,
                    category=spec.name,
                    reason=result.status,
                    detail=result.detail,
                )
            except storage_health.StorageHealthError as exc:
                record = {"error": str(exc)}
            raise StoreReadError(
                f"{spec.name} could not be read ({result.status}); the original file was left untouched",
                status=result.status,
                quarantine=record,
            )
        raw = result.value
        upgraded, persist = _upgrade(raw, spec, path)
        if persist and not _migrate_with_journal(base_dir, spec, path, raw, upgraded):
            return raw
        payload = upgraded if persist else raw
    return payload


def write_store(base_dir: str, spec: StoreSpec, data: Any) -> dict:
    """Stamp the version and write a store atomically under the profile lock."""
    path = store_path(base_dir, spec)
    payload = dict(data) if isinstance(data, dict) else {}
    with profile_locked(base_dir):
        if os.path.isfile(path):
            result = storage_health.read_json_checked(path, dict)
            if not result.ok:
                raise StoreWriteError(f"Cannot overwrite unreadable store: {spec.name}")
            existing = result.value
            if stored_version(existing) > spec.version:
                raise StoreWriteError(
                    f"{spec.name} belongs to a newer Mei build; upgrade before editing it"
                )
        if stored_version(payload) > spec.version:
            raise StoreWriteError(f"Unsupported {spec.name} schema version")
        payload[VERSION_KEY] = spec.version
        write_json(path, payload)
    return payload

"""Stepwise migrations for versioned JSON stores.

Each store declares a current version (``core/store.py``); when a profile on disk
carries an older one, the registered steps run in order — one version at a time —
so an upgrade has a defined path instead of relying on a service's normalizer to
silently reinterpret whatever it finds.

Register a step with the decorator:

    @register("tab_sets.json", from_version=1)
    def _tab_sets_v1_to_v2(data: dict) -> dict:
        ...

The step receives the stored payload and returns the next version's payload; the
framework stamps the new version and persists it once.
"""
from __future__ import annotations

from collections.abc import Callable

MigrationStep = Callable[[dict], dict]

STEPS: dict[str, dict[int, MigrationStep]] = {}


class MissingMigration(RuntimeError):
    """A store is older than this build but no step is registered for it."""


def register(store_name: str, from_version: int):
    """Decorator: ``from_version`` -> ``from_version + 1`` for one store."""

    def decorator(step: MigrationStep) -> MigrationStep:
        STEPS.setdefault(store_name, {})[from_version] = step
        return step

    return decorator


def registered_versions(store_name: str) -> tuple[int, ...]:
    return tuple(sorted(STEPS.get(store_name, {})))


def migrate(store_name: str, data: dict, from_version: int, to_version: int) -> dict:
    """Run every registered step from ``from_version`` up to ``to_version``.

    Raises :class:`MissingMigration` when a hop has no step, so a half-upgraded
    store is never written back.
    """
    version = int(from_version)
    payload = data
    while version < to_version:
        step = STEPS.get(store_name, {}).get(version)
        if step is None:
            raise MissingMigration(
                f"{store_name}: no migration registered from version {version} to {version + 1}"
            )
        result = step(payload)
        if not isinstance(result, dict):
            raise MissingMigration(f"{store_name}: migration from {version} returned {type(result)}")
        payload = result
        version += 1
    return payload

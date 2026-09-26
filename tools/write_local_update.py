"""Publish a built Mei.exe as a local update channel (no server required).

    .venv\\Scripts\\python.exe tools\\write_local_update.py dist

Writes ``dist/update/update.json`` and copies ``dist/Mei.exe`` to
``dist/update/Mei.exe``.  An installed Mei finds that folder on the next launch,
verifies what it contains (``"product": "mei"``, asset name ``Mei.exe``, minimum
size, ``MZ`` header, and the ``sha256`` recorded here) and then replaces its own
executable, keeping one ``.bak`` for the rollback window and deleting the old
build afterwards.

The same manifest shape is what ``tools/publish_release.py`` uploads to GitHub,
so a machine that upgrades from a folder and one that upgrades from the release
channel verify exactly the same facts.

Only a *newer* ``APP_VERSION`` is ever offered, so bump
``litebrowser/core/product.py`` before rebuilding when you want the machine's
existing install to upgrade itself.
"""
import json
import os
import shutil
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litebrowser.core import product  # noqa: E402
from litebrowser.services import update_service  # noqa: E402

USAGE = "usage: write_local_update.py [dist-dir] [--notes \"text\"]"


def manifest_for(exe_path: str, download_url: str, notes: str = "", published_at: str = "") -> dict:
    """The channel manifest for a build: identity, size and sha256.

    Shared with ``tools/publish_release.py`` so both channels describe a build
    the same way — the updater verifies whatever this records.
    """
    return {
        "product": product.PRODUCT_ID,
        "version": product.APP_VERSION,
        "download_url": download_url,
        "sha256": update_service.file_sha256(exe_path),
        "size": os.path.getsize(exe_path),
        "notes": notes or f"{product.APP_VERSION} — {product.PRODUCT_NAME} desktop build.",
        "published_at": published_at or date.today().isoformat(),
    }


def write_local_channel(dist: str, notes: str = "") -> dict:
    """Copy the build into ``dist/update`` and write the manifest beside it."""
    dist = os.path.abspath(dist)
    exe = os.path.join(dist, product.ASSET_NAME)
    if not os.path.isfile(exe):
        raise FileNotFoundError(exe)

    folder = os.path.join(dist, update_service.LOCAL_CHANNEL_DIRNAME)
    os.makedirs(folder, exist_ok=True)
    packaged = os.path.join(folder, product.ASSET_NAME)
    shutil.copyfile(exe, packaged)

    manifest = manifest_for(packaged, packaged, notes)
    manifest_path = os.path.join(folder, update_service.LOCAL_CHANNEL_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    return {"packaged": packaged, "manifest": manifest, "manifest_path": manifest_path}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    notes = ""
    if "--notes" in args:
        index = args.index("--notes")
        try:
            notes = args[index + 1]
        except IndexError:
            print(USAGE)
            return 2
        del args[index : index + 2]

    dist = os.path.abspath(args[0] if args else "dist")
    try:
        written = write_local_channel(dist, notes)
    except FileNotFoundError as exc:
        print(f"Not found: {exc}")
        print("Build first:  build_exe.bat")
        return 1

    packaged = written["packaged"]
    size_mb = os.path.getsize(packaged) / (1024 * 1024)
    print(f"Local update channel ready for {product.PRODUCT_NAME} {product.APP_VERSION}:")
    print(f"  {packaged}  ({size_mb:.0f} MB)")
    print(f"  sha256 {written['manifest']['sha256']}")
    print(f"  {written['manifest_path']}")
    print("An installed Mei older than this version will offer it on its next launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

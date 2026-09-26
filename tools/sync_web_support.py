"""Mirror ``web_support/`` into ``dist/web_support`` for a packaged build.

    .venv\\Scripts\\python.exe tools\\sync_web_support.py
    .venv\\Scripts\\python.exe tools\\sync_web_support.py web_support dist\\web_support

Mei.exe loads the chained sites from the ``web_support`` folder *beside* the exe,
so every build has to refresh it. That used to be ``xcopy`` plus an ``rmdir`` of
the legacy hub copy in ``build_exe.bat`` — but cmd.exe decodes batch lines in the
OEM code page while the file itself is UTF-8, so the diacritics in
``Cục Quản Lý - Bản Đầy Đủ 1`` never matched the real folder name: the dead
~600 MB duplicate was copied into ``dist`` on every build and never pruned.

Doing the mirror in Python keeps the Unicode names intact *and* skips the folder
while walking the source, so the payload is never copied at all. The skip list
comes from ``litebrowser.core.app_paths`` so the build and the running app agree
on which folder names are stale.
"""
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO_ROOT)

try:  # single source of truth for the folder names that are no longer shipped
    from litebrowser.core.app_paths import LEGACY_BUNDLED_FOLDER_MARKERS as SKIP_DIRS
except Exception:  # pragma: no cover - only when the package cannot be imported
    SKIP_DIRS = (
        "Cục Quản Lý - Bản Đầy Đủ 1",
        "Cuc Quan Ly - Ban Day Du 1",
    )

# Dev leftovers that must never ship next to the exe.
SKIP_SUFFIXES = (".log",)


def is_skipped(name: str) -> bool:
    """True for names this build refuses to copy (and prunes from ``dist``)."""
    return name in SKIP_DIRS or name.lower().endswith(SKIP_SUFFIXES)


def prune(dest: str, log=print) -> int:
    """Delete skipped entries older builds left in ``dest``, at any depth.

    Older builds copied the whole folder (dev logs included), so the stale copies
    can sit several levels down — walking ``dest`` is what actually clears them.
    """
    if not os.path.isdir(dest):
        return 0
    removed = 0
    for root, dirs, names in os.walk(dest, topdown=True):
        stale_dirs = [name for name in dirs if is_skipped(name)]
        stale_files = [name for name in names if is_skipped(name)]
        dirs[:] = [name for name in dirs if name not in stale_dirs]
        for name in stale_dirs + stale_files:
            path = os.path.join(root, name)
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except OSError as exc:
                log(f"  could not remove {path}: {exc}")
                continue
            removed += 1
            log(f"  pruned {os.path.relpath(path, dest)}")
    return removed


def sync(source: str, dest: str, log=print) -> tuple[int, int]:
    """Copy ``source`` onto ``dest``, returning (files copied, bytes copied)."""
    os.makedirs(dest, exist_ok=True)
    prune(dest, log)
    files = 0
    total = 0
    for root, dirs, names in os.walk(source, topdown=True):
        dirs[:] = [d for d in dirs if not is_skipped(d)]
        target = dest if root == source else os.path.join(dest, os.path.relpath(root, source))
        os.makedirs(target, exist_ok=True)
        for name in names:
            if is_skipped(name):
                continue
            src_path = os.path.join(root, name)
            if not os.path.isfile(src_path):
                continue
            size = os.path.getsize(src_path)
            try:
                shutil.copy2(src_path, os.path.join(target, name))
            except OSError as exc:
                log(f"  skipped {src_path}: {exc}")
                continue
            files += 1
            total += size
    return files, total


def _utf8_stdout() -> None:
    """Keep the build log readable when a folder name carries diacritics.

    The console code page is cp1252/cp437, so printing ``Cục Quản Lý`` would
    raise UnicodeEncodeError and abort the build halfway through the copy.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _utf8_stdout()
    source = os.path.abspath(args[0] if args else os.path.join(REPO_ROOT, "web_support"))
    dest = os.path.abspath(
        args[1] if len(args) > 1 else os.path.join(REPO_ROOT, "dist", "web_support")
    )
    if not os.path.isdir(source):
        print(f"Not found: {source}")
        return 1
    print(f"Syncing {source}\n      -> {dest}")
    print(f"  not shipping: {', '.join(SKIP_DIRS)}")
    files, total = sync(source, dest)
    print(f"  copied {files} files, {total / (1024 * 1024):.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

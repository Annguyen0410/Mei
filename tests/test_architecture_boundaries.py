"""Architecture boundaries, enforced instead of documented.

``ARCHITECTURE.md`` states the layering (core ← services ← browser/UI) and used to
be the only thing saying so — which is how ``services/brief_service.py`` ended up
importing ``browser/new_tab_page.py`` and made services and browser mutually
dependent. These checks read the real import graph.
"""
import ast
import os
import unittest

PACKAGE = "litebrowser"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Modules that are deliberately not reachable from the entry points. Keep this
# empty: an entry here means dead code is being kept alive by the test.
ALLOWED_ORPHANS: set[str] = set()

LAYERS = ("core", "services", "browser", "ui")

# layer -> layers it must never import from
FORBIDDEN = {
    "core": ("services", "browser", "ui"),
    "services": ("browser", "ui"),
    "browser": ("ui",),
}


def _module_files() -> dict[str, str]:
    modules: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, PACKAGE)):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT)[: -len(".py")].replace(os.sep, ".")
            if rel.endswith(".__init__"):
                rel = rel[: -len(".__init__")]
            modules[rel] = path
    return modules


def _package_of(module: str, is_package_init: bool) -> str:
    if is_package_init:
        return module
    return module.rsplit(".", 1)[0] if "." in module else ""


def _resolved_imports(module: str, path: str, modules: dict[str, str]) -> set[str]:
    """Import targets of one module, resolved to modules that exist here."""
    source = open(path, encoding="utf-8-sig").read()
    tree = ast.parse(source)
    is_init = os.path.basename(path) == "__init__.py"
    found: set[str] = set()
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.ImportFrom):
            if node.level:
                parts = _package_of(module, is_init).split(".")
                up = node.level - 1
                if up:
                    parts = parts[: max(0, len(parts) - up)]
                base = ".".join(parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            targets = [base] + [f"{base}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        for target in targets:
            if not target.startswith(PACKAGE):
                continue
            candidate = target
            while candidate and candidate not in modules:
                candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
            if candidate:
                found.add(candidate)
    return found


class _GraphMixin:
    @classmethod
    def setUpClass(cls):
        cls.modules = _module_files()
        cls.imports = {
            module: _resolved_imports(module, path, cls.modules)
            for module, path in cls.modules.items()
        }

    def layer_of(self, module: str) -> str:
        parts = module.split(".")
        return parts[1] if len(parts) > 1 and parts[1] in LAYERS else ""


class TestLayerDirection(_GraphMixin, unittest.TestCase):
    def test_layers_do_not_import_upwards(self):
        violations: list[str] = []
        for module, targets in sorted(self.imports.items()):
            source_layer = self.layer_of(module)
            if not source_layer:
                continue
            for target in targets:
                target_layer = self.layer_of(target)
                if target_layer and target_layer in FORBIDDEN.get(source_layer, ()):
                    violations.append(f"{module} -> {target}")
        self.assertEqual(violations, [], "layer direction violated")

    def test_services_and_browser_are_not_mutually_dependent(self):
        services_to_browser = {
            module
            for module, targets in self.imports.items()
            if self.layer_of(module) == "services"
            and any(self.layer_of(t) == "browser" for t in targets)
        }
        browser_to_services = {
            module
            for module, targets in self.imports.items()
            if self.layer_of(module) == "browser"
            and any(self.layer_of(t) == "services" for t in targets)
        }
        self.assertFalse(
            services_to_browser and browser_to_services,
            f"services<->browser cycle: {sorted(services_to_browser)} vs {sorted(browser_to_services)}",
        )

    def test_layer_graph_is_acyclic(self):
        edges = {
            (self.layer_of(module), self.layer_of(target))
            for module, targets in self.imports.items()
            for target in targets
            if self.layer_of(module) and self.layer_of(target)
            and self.layer_of(module) != self.layer_of(target)
        }
        for start, _end in edges:
            stack, seen = [start], set()
            while stack:
                node = stack.pop()
                for a, b in edges:
                    if a == node and b not in seen:
                        seen.add(b)
                        stack.append(b)
            self.assertNotIn(start, seen, f"layer cycle back to {start}")


class TestNoOrphanModules(_GraphMixin, unittest.TestCase):
    def test_every_module_is_reachable_from_an_entry_point(self):
        entries = {"litebrowser", "litebrowser.main", "litebrowser.__main__"}
        reachable = {e for e in entries if e in self.modules}
        stack = list(reachable)
        while stack:
            module = stack.pop()
            for target in self.imports.get(module, ()):
                if target not in reachable:
                    reachable.add(target)
                    stack.append(target)
                # Importing a submodule imports its parent packages too.
                parts = target.split(".")
                while len(parts) > 1:
                    parts.pop()
                    parent = ".".join(parts)
                    if parent in self.modules and parent not in reachable:
                        reachable.add(parent)
                        stack.append(parent)

        orphans = sorted(
            module
            for module in self.modules
            if module not in reachable and module not in ALLOWED_ORPHANS
        )
        self.assertEqual(orphans, [], "modules nothing imports — wire them up or delete them")

    def test_allowlist_has_no_stale_entries(self):
        for module in ALLOWED_ORPHANS:
            with self.subTest(module=module):
                self.assertIn(module, self.modules, "allowlisted module no longer exists")


if __name__ == "__main__":
    unittest.main()

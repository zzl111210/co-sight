"""Apply compatibility patches after pip install.

Fixes two Python 3.13 compatibility issues in third-party dependencies:
1. phx-class-registry uses pkg_resources (removed in 3.13)
2. lagent crashes on empty docstrings in newer griffe versions

Run once after `pip install -r requirements.txt`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def patch_class_registry(site_packages: Path) -> bool:
    """Fix pkg_resources import in class_registry/entry_points.py."""
    target = site_packages / "class_registry" / "entry_points.py"
    if not target.is_file():
        print(f"  [SKIP] {target} not found")
        return False

    content = target.read_text(encoding="utf-8")
    if "importlib.metadata" in content:
        print("  [SKIP] Already patched")
        return True

    content = content.replace(
        "from pkg_resources import iter_entry_points",
        """try:
    from pkg_resources import iter_entry_points
except ImportError:
    from importlib.metadata import entry_points

    def iter_entry_points(group):
        eps = entry_points()
        if hasattr(eps, "select"):
            return eps.select(group=group)
        else:
            return eps.get(group, [])""",
    )
    target.write_text(content, encoding="utf-8")
    print("  [PATCHED] class_registry/entry_points.py")
    return True


def patch_lagent(site_packages: Path) -> bool:
    """Fix empty docstring crashes in lagent/actions/base_action.py."""
    target = site_packages / "lagent" / "actions" / "base_action.py"
    if not target.is_file():
        print(f"  [SKIP] {target} not found")
        return False

    content = target.read_text(encoding="utf-8")
    patched = False

    # Fix _parse_tool: docs[0] may not exist
    if "if docs[0].kind is DocstringSectionKind.text" in content and "docs and docs[0]" not in content:
        content = content.replace(
            "if docs[0].kind is DocstringSectionKind.text else ''",
            "if docs and docs[0].kind is DocstringSectionKind.text else ''",
        )
        patched = True

    # Fix ToolMeta.__new__: empty __doc__ may produce empty parse list
    if "description=Docstring(attrs.get('__doc__','')).parse('google')[0].value)" in content:
        content = content.replace(
            "description=Docstring(attrs.get('__doc__','')).parse('google')[0].value)",
            (
                "parsed = Docstring(attrs.get('__doc__', '')).parse('google'); "
                "desc_text = parsed[0].value if parsed else ''"
            ),
        )
        patched = True

    if patched:
        target.write_text(content, encoding="utf-8")
        print("  [PATCHED] lagent/actions/base_action.py")
    else:
        print("  [SKIP] Already patched")
    return patched


def main() -> None:
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    if not site_packages.is_dir():
        # Try Unix-style path
        candidates = list(Path(sys.prefix).glob("lib/python*/site-packages"))
        if candidates:
            site_packages = candidates[0]
        else:
            print(f"ERROR: Cannot find site-packages under {sys.prefix}")
            sys.exit(1)

    print(f"Patching dependencies in: {site_packages}")
    print()

    patch_class_registry(site_packages)
    patch_lagent(site_packages)

    print()
    print("Done. You can now start the server.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fail when a dependency ships under a licence we cannot accept.

Reads a CSV of `name,version,license` rows on stdin -- the shape both
`pip-licenses --format=csv` and `license-checker --csv` produce -- and exits
non-zero if any row matches a denied licence family.

Why not `pip-licenses --fail-on`: that option matches the licence string
*exactly*, so `--fail-on="AGPL"` silently never fires against a package
reporting "GNU Affero General Public License v3". A gate that cannot fire is
worse than no gate, because it looks like protection.

LGPL is deliberately allowed: mitmproxy pulls ldap3 and urwid, and weak
copyleft does not carry the same obligation for a project that merely depends
on them. It is reported, not rejected.
"""

import csv
import re
import sys

# Strong copyleft and non-commercial families, matched case-insensitively as
# substrings. The negative lookbehind keeps LGPL out of the GPL match.
DENIED = re.compile(
    r"(?<![a-z])(?:a?gpl|gnu\s+(?:affero\s+)?general\s+public|sspl|"
    r"server\s+side\s+public|commons\s+clause|non-?commercial|cc-by-nc)",
    re.IGNORECASE,
)
# "LGPL", "GNU Lesser General Public License": weak copyleft, allowed.
ALLOWED_WEAK = re.compile(r"lgpl|lesser\s+general\s+public", re.IGNORECASE)


def _licence_column(header) -> int:
    """Locate the licence column by name.

    The two producers disagree on layout: pip-licenses emits
    `Name,Version,License` while license-checker emits
    `module name,license,repository`. Reading a fixed index silently checked
    npm repository URLs instead of licences.
    """
    for index, cell in enumerate(header):
        if cell.strip().strip('"').lower() == "license":
            return index
    return 2  # headerless input: assume the pip-licenses layout


def _classify(rows, licence_index):
    """Split rows into (denied, weak-copyleft) descriptions."""
    denied, weak = [], []
    for row in rows:
        if len(row) <= licence_index:
            continue
        name, licence = row[0], row[licence_index]
        version = row[1] if licence_index != 1 and len(row) > 1 else ""
        entry = f"{name} {version}: {licence}".replace("  ", " ")
        if ALLOWED_WEAK.search(licence):
            weak.append(entry)
        elif DENIED.search(licence):
            denied.append(entry)
    return denied, weak


def main() -> int:
    rows = list(csv.reader(sys.stdin))
    if not rows:
        print("No packages to check.")
        return 0

    header = rows[0]
    looks_like_header = header and header[0].strip().strip('"').lower() in {
        "name",
        "module name",
    }
    licence_index = _licence_column(header) if looks_like_header else 2
    if looks_like_header:
        rows = rows[1:]

    denied, weak = _classify(rows, licence_index)

    if weak:
        print("Weak copyleft (allowed, listed for awareness):")
        for entry in sorted(weak):
            print(f"  {entry}")

    if denied:
        print("\nDENIED licences found:")
        for entry in sorted(denied):
            print(f"  {entry}")
        print(
            "\nThese carry obligations this project does not accept by default. "
            "Remove the dependency, or add a documented exception here."
        )
        return 1

    print(f"\nNo denied licences across {len(rows)} packages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

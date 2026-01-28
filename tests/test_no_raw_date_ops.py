import os
from pathlib import Path
import unittest

ENFORCE = os.getenv("RAW_DATE_OPS_ENFORCE", "0") == "1"

ALLOWLIST = {
    "dashboard/server/date_kst.py",
}

PATTERNS = [
    (".split(\"T\")", "raw split(T) usage"),
    (".split('T')", "raw split(T) usage"),
    ("LIKE '202", "raw year filter LIKE '202*"),
    ("SUBSTR(", "raw SUBSTR usage"),
    ("substr(", "raw substr usage"),
]


def scan_file(path: Path):
    rel = str(path).replace("\\", "/")
    if rel in ALLOWLIST:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    hits = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        for needle, reason in PATTERNS:
            if needle in line:
                hits.append((rel, i, reason, line.strip()[:200]))
    return hits


class RawDateOpsDetectorTest(unittest.TestCase):
    def test_detect_raw_patterns_non_blocking(self):
        root = Path(__file__).resolve().parents[1]
        targets = []
        targets.extend((root / "dashboard" / "server").rglob("*.py"))
        html = root / "org_tables_v2.html"
        if html.exists():
            targets.append(html)

        hits = []
        for p in targets:
            hits.extend(scan_file(p))

        if hits:
            report = "\n".join(f"{f}:{ln} [{reason}] {code}" for f, ln, reason, code in hits)
            print("\n[raw-date-ops] findings (non-blocking):\n" + report)

        if ENFORCE:
            self.assertFalse(hits, "RAW_DATE_OPS_ENFORCE=1 => raw date ops present\n" + report)


if __name__ == "__main__":
    unittest.main()

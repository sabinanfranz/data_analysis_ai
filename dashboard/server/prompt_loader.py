from __future__ import annotations

from pathlib import Path
from typing import Optional


def load_prompt(
    name: str,
    default_text: str,
    base_dir: Optional[Path] = None,
) -> str:
    """
    Load a prompt file by name from the prompts directory.
    - Ignores leading comment lines starting with '#'.
    - Falls back to default_text if file is missing or unreadable.
    """
    prompts_dir = base_dir or Path(__file__).resolve().parent / "prompts"
    path = prompts_dir / f"{name}.txt"
    try:
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        filtered = []
        for line in lines:
            if line.strip().startswith("#"):
                continue
            filtered.append(line)
        text = "\n".join(filtered).strip()
        return text or default_text
    except Exception:
        return default_text


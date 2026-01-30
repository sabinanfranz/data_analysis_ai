from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict


class PromptStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent / "counterparty_card" / "prompts"

    def _read(self, path: Path, default_text: str = "") -> str:
        try:
            raw = path.read_text(encoding="utf-8")
            lines = []
            for line in raw.splitlines():
                if line.strip().startswith("#"):
                    continue
                lines.append(line)
            text = "\n".join(lines).strip()
            return text or default_text
        except Exception:
            return default_text

    def load_prompt(self, mode_key: str, version: str, kind: str, default_text: str = "") -> str:
        path = self.base_dir / mode_key / version / f"{kind}.txt"
        return self._read(path, default_text)

    def load_set(self, mode_key: str, version: str) -> Dict[str, str]:
        system = self.load_prompt(mode_key, version, "system", "")
        user = self.load_prompt(mode_key, version, "user", "")
        repair = self.load_prompt(mode_key, version, "repair", "")
        prompt_hash = hashlib.sha256(f"{system}\n{user}\n{repair}".encode("utf-8")).hexdigest()
        return {
            "system": system,
            "user": user,
            "repair": repair,
            "prompt_hash": prompt_hash,
        }

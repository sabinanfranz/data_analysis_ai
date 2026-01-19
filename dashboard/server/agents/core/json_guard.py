from __future__ import annotations

import json
from typing import Any, Callable, Tuple


def parse_json(text: str) -> Tuple[Any | None, str | None]:
    try:
        return json.loads(text), None
    except Exception as exc:
        return None, str(exc)


def validate_output(obj: Any, validator: Callable[[Any], None] | None = None) -> Tuple[bool, str | None]:
    try:
        if validator:
            validator(obj)
        return True, None
    except Exception as exc:
        return False, str(exc)


def repair_once(repair_fn: Callable[[str], str], bad_text: str) -> Tuple[Any | None, str | None]:
    try:
        fixed = repair_fn(bad_text)
        return json.loads(fixed), None
    except Exception as exc:
        return None, str(exc)


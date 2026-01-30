from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel


class AnomalyInput(BaseModel):
    variant_key: str
    rows: List[Dict[str, Any]]

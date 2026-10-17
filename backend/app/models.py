"""Modelos de datos compartidos entre servicios."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from .utils.nit import NitResult

ERROR = "error"
WARNING = "warning"

# Estados de parseo de un campo del archivo de origen.
OK = "ok"
EMPTY = "empty"
INVALID = "invalid"


@dataclass
class Issue:
    severity: str                    # "error" | "warning"
    code: str
    message: str
    row: int | None = None           # fila 1-based del archivo de origen
    column: str | None = None        # nombre público de la columna de destino

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "row": self.row,
            "column": self.column,
        }


@dataclass
class Record:
    """Una factura extraída del archivo de origen (antes de escribir el Excel)."""

    source_row: int
    raw: dict[str, Any] = field(default_factory=dict)       # valores crudos por clave
    status: dict[str, str] = field(default_factory=dict)    # clave -> ok | empty | invalid
    detail: dict[str, str] = field(default_factory=dict)    # clave -> motivo de invalidez
    nit: NitResult | None = None
    name: str = ""
    invoice: str = ""
    issue_date: date | None = None
    amount: Decimal | None = None
    solunion_code: str | None = None
    debtor_reference: str | None = None
    payment_condition: str | None = None
    # Derivados (siempre calculados, nunca copiados del archivo de origen)
    due_date: date | None = None
    term: int | None = None
    document_type: str = ""
    country: str = ""

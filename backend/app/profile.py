"""Carga y validación del perfil de procesamiento (JSON) de una plantilla."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import PROFILES_DIR, TEMPLATES_DIR
from .utils.text import normalize_header

VALID_ROLES = {"source", "constant", "derived", "optional"}


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    letter: str
    header: str                 # texto EXACTO de la plantilla (con espacios/saltos de línea)
    kind: str                   # text | date | int | decimal
    role: str                   # source | constant | derived | optional
    required: bool
    aliases: tuple[str, ...]    # ya normalizados, en orden de prioridad
    constant: Any = None
    assume_dv_headers: tuple[str, ...] = ()

    @property
    def index(self) -> int:
        """Posición 1-based de la columna dentro de la hoja."""
        value = 0
        for ch in self.letter:
            value = value * 26 + (ord(ch) - 64)
        return value

    @property
    def public_name(self) -> str:
        """Nombre legible para el usuario (sin saltos de línea ni espacios sobrantes)."""
        return " ".join(self.header.split())

    @property
    def maps_from_source(self) -> bool:
        """Columnas que se intentan localizar en el archivo de entrada."""
        return bool(self.aliases) and self.role in {"source", "optional", "derived"}


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    template_path: Path
    sheet: str
    auxiliary_sheets: tuple[str, ...]
    header_row: int
    first_data_row: int
    style_prototype_row: int
    style_columns: int
    output_name_prefix: str
    fallback_output_name: str
    constants: dict[str, Any]
    rules: dict[str, Any]
    columns: tuple[ColumnSpec, ...]
    by_key: dict[str, ColumnSpec] = field(default_factory=dict, compare=False, repr=False)

    def column(self, key: str) -> ColumnSpec:
        return self.by_key[key]

    @property
    def headers(self) -> list[str]:
        return [c.header for c in self.columns]

    @property
    def required_keys(self) -> list[str]:
        return [c.key for c in self.columns if c.required and c.role == "source"]


def _build_column(raw: dict[str, Any]) -> ColumnSpec:
    role = raw["role"]
    if role not in VALID_ROLES:
        raise ValueError(f"Rol inválido en el perfil: {role}")
    # Las columnas constantes no se buscan en el archivo de entrada. El resto
    # reconoce sus alias y, con menor prioridad, el encabezado oficial de la plantilla.
    candidates = [] if role == "constant" else [*raw.get("aliases", []), raw["header"]]
    aliases: list[str] = []
    for text in candidates:
        normalized = normalize_header(text)
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return ColumnSpec(
        key=raw["key"],
        letter=raw["letter"],
        header=raw["header"],
        kind=raw["type"],
        role=role,
        required=bool(raw.get("required", False)),
        aliases=tuple(aliases),
        constant=raw.get("constant"),
        assume_dv_headers=tuple(normalize_header(h) for h in raw.get("assume_dv_headers", [])),
    )


def load_profile(path: Path) -> Profile:
    data = json.loads(path.read_text(encoding="utf-8"))
    columns = tuple(_build_column(c) for c in data["columns"])
    keys = [c.key for c in columns]
    if len(set(keys)) != len(keys):
        raise ValueError("Claves de columna duplicadas en el perfil")
    return Profile(
        id=data["id"],
        label=data["label"],
        template_path=TEMPLATES_DIR / data["template"],
        sheet=data["sheet"],
        auxiliary_sheets=tuple(data.get("auxiliary_sheets", [])),
        header_row=int(data["header_row"]),
        first_data_row=int(data["first_data_row"]),
        style_prototype_row=int(data["style_prototype_row"]),
        style_columns=int(data["style_columns"]),
        output_name_prefix=data["output_name_prefix"],
        fallback_output_name=data["fallback_output_name"],
        constants=dict(data["constants"]),
        rules=dict(data["rules"]),
        columns=columns,
        by_key={c.key: c for c in columns},
    )


@lru_cache(maxsize=8)
def get_profile(profile_id: str = "declaracion_ventas") -> Profile:
    return load_profile(PROFILES_DIR / f"{profile_id}.json")

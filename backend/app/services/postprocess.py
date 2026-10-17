"""Post-proceso del .xlsx guardado por openpyxl: cadenas en ``sharedStrings.xml``.

openpyxl escribe los textos como ``inlineStr``. Es OOXML válido, pero los archivos
que la plataforma destino ya aceptó (los exportados por Excel) usan la tabla de
cadenas compartidas. Para minimizar riesgos de compatibilidad con el lector de la
plataforma, se reemplazan las celdas ``inlineStr`` por referencias a
``xl/sharedStrings.xml``. Si algo falla, el archivo original queda intacto.
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger("ingeslingas.postprocess")

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
SHARED_STRINGS_PART = "xl/sharedStrings.xml"
SHARED_STRINGS_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
SHARED_STRINGS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
_SHEET_PART = re.compile(r"xl/worksheets/sheet\d+\.xml")

ET.register_namespace("", NS_MAIN)


def use_shared_strings(path: Path) -> bool:
    """Reescribe ``path`` usando sharedStrings. Devuelve True si hubo cambios."""
    try:
        return _rewrite(path)
    except Exception:  # el archivo de openpyxl ya es válido; no se bloquea el flujo
        logger.exception("No se pudo convertir a sharedStrings; se conserva el archivo original")
        return False


def _rewrite(path: Path) -> bool:
    with zipfile.ZipFile(path) as source:
        names = source.namelist()
        if SHARED_STRINGS_PART in names:
            return False
        table: dict[str, int] = {}
        order: list[str] = []
        refs = [0]
        parts: dict[str, bytes] = {}
        changed = False

        for name in names:
            data = source.read(name)
            if _SHEET_PART.fullmatch(name) and b"inlineStr" in data:
                data = _convert_sheet(data, table, order, refs)
                changed = True
            parts[name] = data

        if not changed:
            return False

        parts[SHARED_STRINGS_PART] = _shared_strings_xml(order, refs[0])
        parts["[Content_Types].xml"] = _add_content_type(parts["[Content_Types].xml"])
        parts["xl/_rels/workbook.xml.rels"] = _add_relationship(parts["xl/_rels/workbook.xml.rels"])
        infos = {info.filename: info for info in source.infolist()}

    fd, tmp_name = tempfile.mkstemp(suffix=".xlsx", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(open(fd, "wb"), "w", zipfile.ZIP_DEFLATED) as target:
            # [Content_Types].xml primero, como hacen Excel y openpyxl.
            for name in ["[Content_Types].xml"] + [n for n in parts if n != "[Content_Types].xml"]:
                info = infos.get(name)
                target.writestr(zipfile.ZipInfo(name, date_time=info.date_time if info else (1980, 1, 1, 0, 0, 0)),
                                parts[name], compress_type=zipfile.ZIP_DEFLATED)
        shutil.move(str(tmp), str(path))
    finally:
        tmp.unlink(missing_ok=True)
    return True


def _convert_sheet(data: bytes, table: dict[str, int], order: list[str], refs: list[int]) -> bytes:
    root = ET.fromstring(data)
    q = lambda tag: f"{{{NS_MAIN}}}{tag}"  # noqa: E731
    for cell in root.iter(q("c")):
        if cell.get("t") != "inlineStr":
            continue
        inline = cell.find(q("is"))
        text_node = inline.find(q("t")) if inline is not None else None
        if inline is None or text_node is None or len(inline) != 1:
            raise ValueError("Cadena inline con formato enriquecido; no se convierte")
        text = text_node.text or ""
        index = table.get(text)
        if index is None:
            index = len(order)
            table[text] = index
            order.append(text)
        refs[0] += 1
        cell.remove(inline)
        cell.set("t", "s")
        value = ET.SubElement(cell, q("v"))
        value.text = str(index)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _shared_strings_xml(order: list[str], refs: int) -> bytes:
    root = ET.Element(f"{{{NS_MAIN}}}sst", {"count": str(refs), "uniqueCount": str(len(order))})
    for text in order:
        item = ET.SubElement(root, f"{{{NS_MAIN}}}si")
        node = ET.SubElement(item, f"{{{NS_MAIN}}}t")
        node.text = text
        if text != text.strip() or "\n" in text or "\r" in text or "  " in text:
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _add_content_type(data: bytes) -> bytes:
    ET.register_namespace("", NS_CT)
    root = ET.fromstring(data)
    override = ET.SubElement(root, f"{{{NS_CT}}}Override")
    override.set("PartName", "/" + SHARED_STRINGS_PART)
    override.set("ContentType", SHARED_STRINGS_TYPE)
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ET.register_namespace("", NS_MAIN)
    return result


def _add_relationship(data: bytes) -> bytes:
    ET.register_namespace("", NS_REL)
    root = ET.fromstring(data)
    ids = {rel.get("Id") for rel in root}
    number = 1
    while f"rId{number}" in ids:
        number += 1
    rel = ET.SubElement(root, f"{{{NS_REL}}}Relationship")
    rel.set("Id", f"rId{number}")
    rel.set("Type", SHARED_STRINGS_REL)
    rel.set("Target", "sharedStrings.xml")
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ET.register_namespace("", NS_MAIN)
    return result

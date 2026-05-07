import logging
import xml.etree.ElementTree as ET

from .errors import AdaptiveError
from .schema import adaptive_to_dss_type, coerce_value

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = ("modeled", "cube", "standard", "transaction")


_SHEET_TAG_SUFFIX = "-sheet"


def _sheet_type_from_tag(tag):
    if tag == "sheet":
        return ""
    if tag.endswith(_SHEET_TAG_SUFFIX):
        return tag[: -len(_SHEET_TAG_SUFFIX)].lower()
    return ""


def list_sheets(client):
    """Return every sheet visible to the credentials.

    Adaptive returns one element per sheet, with the type encoded in the tag
    name (e.g. <standard-sheet>, <cube-sheet>, <modeled-sheet>).

    Each item: {"id": str, "type": str, "code": str, "name": str}.
    """
    root = client.post("exportSheets")
    sheets = []
    for el in root.iter():
        sheet_type = _sheet_type_from_tag(el.tag)
        explicit_type = (el.get("type") or "").lower()
        sheet_type = sheet_type or explicit_type
        if not sheet_type and el.tag != "sheet":
            continue
        sheet_id = el.get("id") or el.get("ID")
        if not sheet_id:
            continue
        is_global = (el.get("isGlobal") or "").strip()
        sheets.append({
            "id": str(sheet_id),
            "type": sheet_type,
            "code": el.get("code") or "",
            "name": el.get("name") or el.get("code") or sheet_id,
            "is_global": is_global in ("1", "true", "True"),
        })
    sheets.sort(key=lambda s: (s["type"], s["name"].lower()))
    return sheets


def get_sheet_schema(client, sheet):
    """Return None so Dataiku infers the schema from the first rows.

    For all sheet types Adaptive's export response is CSV; we don't have a
    reliable schema-pre-fetch path that lines up with the column names the
    CSV actually emits, so it's safer to let DSS infer column types from the
    yielded rows than to declare a schema that may not match.
    """
    return None


def _column_index(schema):
    if not schema:
        return {}
    return {col["name"]: col.get("type", "string") for col in schema.get("columns", [])}


def _version_element(version):
    if version:
        return [ET.Element("version", {"name": str(version)})]
    return []


def _resolve_default_version(client):
    """Return the default version name as configured in the Adaptive instance.

    Adaptive's exportData requires <version>; we call exportVersions and pick
    the version flagged default, falling back to the first version we find.
    """
    root = client.post("exportVersions")
    candidates = []
    for el in root.iter():
        if "version" not in el.tag.lower():
            continue
        name = el.get("name")
        if not name:
            continue
        is_default = (el.get("isDefaultVersion") or el.get("isDefault") or "").lower() in ("1", "true")
        candidates.append((is_default, name))
    if not candidates:
        raise AdaptiveError(
            "No versions returned by exportVersions; specify a version explicitly in the dataset config"
        )
    candidates.sort(key=lambda c: 0 if c[0] else 1)
    return candidates[0][1]


def export_rows(client, sheet, version=None, records_limit=-1, cube_filters=None):
    """Yield rows from the sheet as dicts keyed by column name.

    cube_filters: only used when sheet["type"] == "cube". Dict with keys
        accounts (list of codes), levels (list of codes), time_start (str),
        time_end (str), dimensions (list of names — which dims to include in
        the output columns).
    """
    sheet_type = sheet.get("type")
    if sheet_type == "modeled":
        yield from _export_modeled(client, sheet, version=version, records_limit=records_limit)
    elif sheet_type == "cube":
        yield from _export_cube(client, sheet, version=version,
                                cube_filters=cube_filters or {},
                                records_limit=records_limit)
    elif sheet_type in ("standard", "transaction"):
        yield from _export_data(client, sheet, version=version, records_limit=records_limit)
    else:
        raise AdaptiveError("Unsupported sheet type: {}".format(sheet_type))


_CONFIGURABLE_SHEET_DEFAULTS = {
    "includeAllColumns": "true",
    "isGetAllRows": "true",
    "useNumericIDs": "false",
    # Adaptive's schema has a typo here ("diplsay" rather than "display"); the
    # parser rejects the corrected spelling. Keep it false so the response
    # works regardless of whether the sheet itself has display names enabled
    # — when it is true, the include* attrs become required, and they're
    # rejected on sheets that have display names disabled.
    "diplsayNameEnabled": "false",
    "useAccountPrecision": "false",
    "useActualValue": "false",
}


def _configurable_sheet_element(tag, sheet):
    attrs = {
        "name": sheet.get("name") or sheet.get("code") or str(sheet["id"]),
        "isGlobal": "true" if sheet.get("is_global") else "false",
    }
    attrs.update(_CONFIGURABLE_SHEET_DEFAULTS)
    return ET.Element(tag, attrs)


def _export_modeled(client, sheet, version=None, records_limit=-1):
    if not version:
        version = _resolve_default_version(client)
    body = [
        ET.Element("version", {"name": str(version)}),
        _configurable_sheet_element("modeled-sheet", sheet),
    ]
    root = client.post("exportConfigurableModelData", body)
    yield from _yield_csv_output(root, records_limit=records_limit, data_path="output/data")


def _export_data(client, sheet, version=None, records_limit=-1):
    if not version:
        version = _resolve_default_version(client)
    body = [ET.Element("version", {"name": str(version)})]
    body.append(ET.Element("format", {
        "useInternalCodes": "true",
        "includeUnmappedItems": "false",
        "displayNameEnabled": "false",
    }))
    body.append(ET.Element("rules", {
        "includeRollupAccounts": "false",
        "includeRollupLevels": "false",
        "includeZeroRows": "false",
        "markBlanks": "false",
        "markInvalidValues": "false",
        "timeRollups": "false",
    }))
    root = client.post("exportData", body)
    yield from _yield_csv_output(root, records_limit=records_limit)


def _export_cube(client, sheet, version=None, cube_filters=None, records_limit=-1):
    cube_filters = cube_filters or {}
    accounts = [a for a in (cube_filters.get("accounts") or []) if a]
    levels = [l for l in (cube_filters.get("levels") or []) if l]
    time_start = (cube_filters.get("time_start") or "").strip()
    time_end = (cube_filters.get("time_end") or "").strip()
    dimensions = [d for d in (cube_filters.get("dimensions") or []) if d]

    missing = []
    if not accounts:
        missing.append("accounts")
    if not levels:
        missing.append("levels")
    if not time_start or not time_end:
        missing.append("time span (start and end)")
    if missing:
        raise AdaptiveError(
            "Cube sheet export requires {}. Set them on the dataset config.".format(
                ", ".join(missing)
            )
        )

    if not version:
        version = _resolve_default_version(client)

    body = [
        ET.Element("version", {"name": str(version)}),
        ET.Element("format", {
            "useInternalCodes": "true",
            "includeUnmappedItems": "false",
            "displayNameEnabled": "false",
            "includeCodes": "true",
            "includeNames": "true",
        }),
    ]

    filters = ET.Element("filters")
    accounts_el = ET.SubElement(filters, "accounts")
    for code in accounts:
        ET.SubElement(accounts_el, "account", {
            "code": code,
            "isAssumption": "0",
            "includeDescendants": "true",
        })
    levels_el = ET.SubElement(filters, "levels")
    for code in levels:
        ET.SubElement(levels_el, "level", {
            "code": code,
            "isRollup": "0",
            "includeDescendants": "true",
        })
    ET.SubElement(filters, "timeSpan", {"start": time_start, "end": time_end})
    body.append(filters)

    if dimensions:
        dims_el = ET.Element("dimensions")
        for d in dimensions:
            ET.SubElement(dims_el, "dimension", {"name": d})
        body.append(dims_el)

    body.append(ET.Element("rules", {
        "includeRollupAccounts": "false",
        "includeRollupLevels": "false",
        "includeZeroRows": "false",
        "markBlanks": "false",
        "markInvalidValues": "false",
        "timeRollups": "false",
    }))

    root = client.post("exportData", body)
    yield from _yield_csv_output(root, records_limit=records_limit)


def _yield_csv_output(root, records_limit=-1, data_path="output"):
    """Find the first CSV-bearing element in the response and yield rows.

    Adaptive's exportData and exportConfigurableModelData responses both
    deliver CSV inside a text node, but the wrapping element varies across
    API versions and methods. Try the explicit hint first, then fall back
    to scanning every element whose text looks like a multi-line, multi-
    column CSV with at least one data row. If nothing usable is present,
    raise with the raw response so the caller can see what came back.
    """
    import csv
    import io

    text = _find_csv_text(root, data_path)
    if text is None:
        raise AdaptiveError(
            "Adaptive returned success but no CSV data was found in the "
            "response. Raw response: {}".format(_truncate_xml(root))
        )
    reader = csv.DictReader(io.StringIO(text), lineterminator="\n")
    yielded = 0
    for row in reader:
        yield {k: coerce_value(v, "string") for k, v in row.items()}
        yielded += 1
        if 0 < records_limit <= yielded:
            return


def _truncate_xml(root, limit=2000):
    raw = ET.tostring(root, encoding="unicode")
    if len(raw) > limit:
        return raw[:limit] + "...(truncated)"
    return raw


def _find_csv_text(root, hint_path):
    candidates = []
    if hint_path:
        el = root.find(hint_path)
        if el is not None:
            candidates.append(el)
    candidates.append(root.find("output"))
    candidates.extend(root.iter())
    seen = set()
    for el in candidates:
        if el is None or id(el) in seen:
            continue
        seen.add(id(el))
        if el.text is None:
            continue
        text = el.text.strip()
        if not text:
            continue
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        first_line = lines[0]
        if first_line.count(",") < 1:
            continue
        return "\n".join(lines)
    return None


def import_rows(client, sheet, schema, rows, version=None, mode="REPLACE", batch_size=5000, dry_run=False):
    """Push rows into the sheet, batching to keep payloads bounded.

    mode: "REPLACE" or "APPEND". Only meaningful for modeled sheets.
    """
    sheet_type = sheet.get("type")
    if sheet_type == "modeled":
        return _import_modeled(client, sheet, schema, rows, version=version, mode=mode,
                               batch_size=batch_size, dry_run=dry_run)
    if sheet_type == "cube":
        return _import_cube(client, sheet, schema, rows, version=version,
                            batch_size=batch_size, dry_run=dry_run)
    if sheet_type == "standard":
        return _import_standard(client, sheet, schema, rows, version=version,
                                batch_size=batch_size, dry_run=dry_run)
    raise AdaptiveError("Import is not supported for sheet type: {}".format(sheet_type))


def _flush_batch(client, method, sheet, schema, rows, version, mode, container_tag, container_attrs, dry_run):
    if not rows:
        return 0
    container = ET.Element(container_tag, container_attrs)
    rows_el = ET.SubElement(container, "rows")
    columns = [c["name"] for c in schema.get("columns", [])]
    for row in rows:
        row_el = ET.SubElement(rows_el, "row")
        for col in columns:
            value = row.get(col)
            ET.SubElement(row_el, "column", {
                "name": col,
                "value": "" if value is None else str(value),
            })
    body = [container]
    body.extend(_version_element(version))
    if mode:
        opt = ET.Element("insertOption")
        opt.text = mode.upper()
        body.append(opt)
    if dry_run:
        logger.info("[dry_run] %s would post %d rows to sheet %s", method, len(rows), sheet.get("id"))
        return len(rows)
    client.post(method, body)
    return len(rows)


def _import_modeled(client, sheet, schema, rows, version, mode, batch_size, dry_run):
    return _drain(rows, batch_size, lambda batch: _flush_batch(
        client, "importConfigurableModelData", sheet, schema, batch, version, mode,
        "modeled-sheet", {"id": str(sheet["id"])}, dry_run,
    ))


def _import_cube(client, sheet, schema, rows, version, batch_size, dry_run):
    return _drain(rows, batch_size, lambda batch: _flush_batch(
        client, "importCubeData", sheet, schema, batch, version, None,
        "cube-sheet", {"id": str(sheet["id"])}, dry_run,
    ))


def _import_standard(client, sheet, schema, rows, version, batch_size, dry_run):
    return _drain(rows, batch_size, lambda batch: _flush_batch(
        client, "importStandardData", sheet, schema, batch, version, None,
        "standard-sheet", {"id": str(sheet["id"])}, dry_run,
    ))


def _drain(rows, batch_size, flush):
    total = 0
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            total += flush(batch)
            batch = []
    if batch:
        total += flush(batch)
    return total

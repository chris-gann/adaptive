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
        sheets.append({
            "id": str(sheet_id),
            "type": sheet_type,
            "code": el.get("code") or "",
            "name": el.get("name") or el.get("code") or sheet_id,
        })
    sheets.sort(key=lambda s: (s["type"], s["name"].lower()))
    return sheets


def get_sheet_schema(client, sheet):
    """Return DSS-shaped schema dict for the sheet.

    Modeled and cube sheets use exportSheetDefinition.
    Standard / transaction sheets fall back to a generic schema since their
    "columns" are really account/level/period/value coordinates.
    """
    sheet_type = sheet.get("type")
    if sheet_type in ("modeled", "cube"):
        body = [ET.Element("sheet", {"ID": str(sheet["id"])})]
        root = client.post("exportSheetDefinition", body)
        columns = []
        for col in root.iter("column"):
            name = col.get("name") or col.get("code")
            if not name:
                continue
            columns.append({
                "name": name,
                "type": adaptive_to_dss_type(col.get("type")),
            })
        if columns:
            return {"columns": columns}
    return {"columns": [
        {"name": "account_code", "type": "string"},
        {"name": "account_name", "type": "string"},
        {"name": "level_code", "type": "string"},
        {"name": "time_period", "type": "string"},
        {"name": "value", "type": "double"},
    ]}


def _column_index(schema):
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


def export_rows(client, sheet, version=None, records_limit=-1):
    """Yield rows from the sheet as dicts keyed by column name."""
    sheet_type = sheet.get("type")
    if sheet_type == "modeled":
        yield from _export_modeled(client, sheet, version=version, records_limit=records_limit)
    elif sheet_type in ("cube", "standard", "transaction"):
        yield from _export_data(client, sheet, version=version, records_limit=records_limit)
    else:
        raise AdaptiveError("Unsupported sheet type: {}".format(sheet_type))


def _export_modeled(client, sheet, version=None, records_limit=-1):
    body = [ET.Element("modeledSheet", {"ID": str(sheet["id"])})]
    body.extend(_version_element(version))
    root = client.post("exportConfigurableModelData", body)
    schema = get_sheet_schema(client, sheet)
    type_by_col = _column_index(schema)
    yielded = 0
    for row_el in root.iter("row"):
        row = {}
        for col_el in row_el.findall("column"):
            name = col_el.get("name") or col_el.get("code")
            if not name:
                continue
            row[name] = coerce_value(
                col_el.get("value") if col_el.get("value") is not None else (col_el.text or ""),
                type_by_col.get(name, "string"),
            )
        if not row:
            continue
        yield row
        yielded += 1
        if 0 < records_limit <= yielded:
            return


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
    if sheet.get("type") == "cube":
        filters = ET.Element("filters")
        ET.SubElement(filters, "cubeSheet", {"ID": str(sheet["id"])})
        body.append(filters)
    root = client.post("exportData", body)
    yielded = 0
    output_text = None
    output_el = root.find(".//output")
    if output_el is not None:
        output_text = (output_el.text or "").strip()
    if not output_text:
        return
    import base64
    try:
        decoded = base64.b64decode(output_text).decode("utf-8", errors="replace")
    except Exception:
        decoded = output_text
    import csv
    import io
    reader = csv.DictReader(io.StringIO(decoded))
    for row in reader:
        yield {k: coerce_value(v, "string") for k, v in row.items()}
        yielded += 1
        if 0 < records_limit <= yielded:
            return


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
        "modeledSheet", {"ID": str(sheet["id"])}, dry_run,
    ))


def _import_cube(client, sheet, schema, rows, version, batch_size, dry_run):
    return _drain(rows, batch_size, lambda batch: _flush_batch(
        client, "importCubeData", sheet, schema, batch, version, None,
        "cubeSheet", {"ID": str(sheet["id"])}, dry_run,
    ))


def _import_standard(client, sheet, schema, rows, version, batch_size, dry_run):
    return _drain(rows, batch_size, lambda batch: _flush_batch(
        client, "importStandardData", sheet, schema, batch, version, None,
        "standardSheet", {"ID": str(sheet["id"])}, dry_run,
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

import logging

from dataiku.exporter import Exporter

from adaptivetest import (
    AdaptiveClient,
    AdaptiveError,
    SUPPORTED_TYPES,
    import_rows,
    list_sheets,
)

logger = logging.getLogger(__name__)


def _parse_sheet_value(value):
    if not value or ":" not in value:
        raise ValueError("Invalid sheet selector '{}': pick a sheet from the dropdown".format(value))
    sheet_type, sheet_id = value.split(":", 1)
    sheet_type = sheet_type.lower()
    if sheet_type not in SUPPORTED_TYPES:
        raise ValueError("Unsupported sheet type '{}'".format(sheet_type))
    return sheet_type, sheet_id


def _resolve_sheet(client, sheet_type, sheet_id):
    for s in list_sheets(client):
        if s["type"] == sheet_type and str(s["id"]) == str(sheet_id):
            return s
    return {"id": sheet_id, "type": sheet_type, "code": "", "name": sheet_id}


class AdaptiveSheetExporter(Exporter):
    def __init__(self, config, plugin_config):
        self.config = config
        self.plugin_config = plugin_config
        sheet_type, sheet_id = _parse_sheet_value(self.config.get("sheet"))
        self._client = AdaptiveClient.from_preset(self.config.get("credentials") or {})
        self._sheet = _resolve_sheet(self._client, sheet_type, sheet_id)
        self._version = (self.config.get("version") or "").strip() or None
        self._mode = (self.config.get("mode") or "REPLACE").upper()
        try:
            self._batch_size = max(1, int(self.config.get("batch_size") or 5000))
        except (TypeError, ValueError):
            self._batch_size = 5000
        self._dry_run = bool(self.config.get("dry_run"))
        self._schema = None
        self._column_names = []
        self._buffer = []
        self._total = 0

    def open(self, schema):
        self._schema = schema
        self._column_names = [c["name"] for c in schema.get("columns", [])]
        logger.info(
            "Adaptive export opening sheet=%s/%s columns=%d batch=%d dry_run=%s mode=%s",
            self._sheet.get("type"), self._sheet.get("id"),
            len(self._column_names), self._batch_size, self._dry_run, self._mode,
        )

    def write_row(self, row):
        record = {name: row[i] if i < len(row) else None
                  for i, name in enumerate(self._column_names)}
        self._buffer.append(record)
        if len(self._buffer) >= self._batch_size:
            self._flush()

    def close(self):
        if self._buffer:
            self._flush()
        logger.info("Adaptive export finished: %d rows pushed to %s",
                    self._total, self._sheet.get("name") or self._sheet.get("id"))

    def _flush(self):
        if not self._buffer:
            return
        try:
            pushed = import_rows(
                self._client, self._sheet, self._schema, iter(self._buffer),
                version=self._version, mode=self._mode,
                batch_size=len(self._buffer), dry_run=self._dry_run,
            )
        except AdaptiveError as exc:
            raise RuntimeError("Adaptive import failed: {}".format(exc))
        self._total += pushed or 0
        self._buffer = []

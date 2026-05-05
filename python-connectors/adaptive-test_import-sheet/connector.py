import logging

from dataiku.connector import Connector

from adaptivetest import (
    AdaptiveClient,
    AdaptiveError,
    SUPPORTED_TYPES,
    export_rows,
    get_sheet_schema,
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


class AdaptiveSheetConnector(Connector):
    def __init__(self, config, plugin_config):
        Connector.__init__(self, config, plugin_config)
        sheet_type, sheet_id = _parse_sheet_value(self.config.get("sheet"))
        self._client = AdaptiveClient.from_preset(self.config.get("credentials") or {})
        self._sheet = _resolve_sheet(self._client, sheet_type, sheet_id)
        self._version = (self.config.get("version") or "").strip() or None
        self._cube_filters = {
            "accounts": self.config.get("accounts") or [],
            "levels": self.config.get("levels") or [],
            "dimensions": self.config.get("dimensions") or [],
            "time_start": (self.config.get("time_start") or "").strip(),
            "time_end": (self.config.get("time_end") or "").strip(),
        } if sheet_type == "cube" else None

    def get_read_schema(self):
        try:
            return get_sheet_schema(self._client, self._sheet)
        except AdaptiveError as exc:
            logger.warning("Could not fetch sheet schema, will infer from rows: %s", exc)
            return None

    def generate_rows(self, dataset_schema=None, dataset_partitioning=None,
                      partition_id=None, records_limit=-1):
        for row in export_rows(self._client, self._sheet,
                               version=self._version,
                               records_limit=records_limit,
                               cube_filters=self._cube_filters):
            yield row

    def get_writer(self, dataset_schema=None, dataset_partitioning=None,
                   partition_id=None, write_mode="OVERWRITE"):
        raise NotImplementedError("Use the 'Export Adaptive Sheet' exporter to write to Adaptive.")

    def get_partitioning(self):
        raise NotImplementedError

    def list_partitions(self, partitioning):
        return []

    def partition_exists(self, partitioning, partition_id):
        raise NotImplementedError

    def get_records_count(self, partitioning=None, partition_id=None):
        raise NotImplementedError

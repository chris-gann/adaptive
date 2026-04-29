_TYPE_MAP = {
    "NUMERIC": "double",
    "NUMBER": "double",
    "DECIMAL": "double",
    "INTEGER": "bigint",
    "INT": "bigint",
    "TEXT": "string",
    "STRING": "string",
    "DATE": "date",
    "DATETIME": "date",
    "BOOLEAN": "boolean",
    "BOOL": "boolean",
    "ACCOUNT": "string",
    "LEVEL": "string",
    "DIMENSION": "string",
    "ATTRIBUTE": "string",
}


def adaptive_to_dss_type(adaptive_type):
    if adaptive_type is None:
        return "string"
    return _TYPE_MAP.get(str(adaptive_type).upper(), "string")


def coerce_value(value, dss_type):
    if value is None or value == "":
        return None
    if dss_type == "double":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if dss_type == "bigint":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
    if dss_type == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "y"):
            return True
        if s in ("0", "false", "no", "n"):
            return False
        return None
    return str(value)

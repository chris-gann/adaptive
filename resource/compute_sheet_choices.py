from adaptivetest import (
    AdaptiveClient,
    AdaptiveError,
    list_accounts,
    list_dimensions,
    list_levels,
    list_sheets,
)


def do(payload, config, plugin_config, inputs):
    creds = config.get("credentials") or {}
    if not all(creds.get(k) for k in ("instance_code", "username", "password")):
        return {"choices": [{"value": "", "label": "Select a credentials preset first"}]}

    name = (payload or {}).get("parameterName") or ""
    try:
        client = AdaptiveClient.from_preset(creds)
        if name == "sheet":
            return _sheet_choices(client, (config.get("sheet_type") or "").lower())
        if name in ("accounts", "levels", "dimensions"):
            return _metadata_choices(client, name)
    except AdaptiveError as exc:
        return {"choices": [{"value": "", "label": "Error loading {}: {}".format(name or "choices", exc)}]}
    except Exception as exc:
        return {"choices": [{"value": "", "label": "Error: {}".format(exc)}]}
    return {"choices": []}


def _sheet_choices(client, sheet_type):
    sheets = list_sheets(client)
    if sheet_type:
        sheets = [s for s in sheets if s["type"] == sheet_type]
    if not sheets:
        return {"choices": [{"value": "", "label": "No {} sheets found".format(sheet_type or "")}]}
    return {"choices": [
        {
            "value": "{}:{}".format(s["type"], s["id"]),
            "label": "{} ({})".format(s["name"], s["code"] or s["id"]),
        }
        for s in sheets
    ]}


def _metadata_choices(client, kind):
    if kind == "accounts":
        items = list_accounts(client)
    elif kind == "levels":
        items = list_levels(client)
    elif kind == "dimensions":
        items = list_dimensions(client)
    else:
        items = []
    if not items:
        return {"choices": [{"value": "", "label": "No {} found".format(kind)}]}
    return {"choices": [
        {"value": item["code"], "label": "{} ({})".format(item["name"], item["code"])}
        for item in items
    ]}

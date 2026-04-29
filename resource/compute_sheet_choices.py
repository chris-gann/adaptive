from adaptivetest import AdaptiveClient, AdaptiveError, list_sheets


def do(payload, config, plugin_config, inputs):
    creds = config.get("credentials") or {}
    if not all(creds.get(k) for k in ("instance_code", "username", "password")):
        return {"choices": [{"value": "", "label": "Select a credentials preset first"}]}
    try:
        client = AdaptiveClient.from_preset(creds)
        sheets = list_sheets(client)
    except AdaptiveError as exc:
        return {"choices": [{"value": "", "label": "Error loading sheets: {}".format(exc)}]}
    except Exception as exc:
        return {"choices": [{"value": "", "label": "Error: {}".format(exc)}]}
    if not sheets:
        return {"choices": [{"value": "", "label": "No sheets found in this instance"}]}
    return {"choices": [
        {
            "value": "{}:{}".format(s["type"], s["id"]),
            "label": "{} ({})".format(s["name"], s["code"] or s["id"]),
            "group": s["type"].title() if s["type"] else "Other",
        }
        for s in sheets
    ]}

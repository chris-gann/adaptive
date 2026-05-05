"""Metadata listing helpers used by the cube-sheet filter dropdowns.

Accounts and levels are hierarchical in Adaptive; we recursively walk every
descendant element so the choice provider sees a flat list. Dimensions carry
nested dimension values, but for filter UX we only return the dimensions —
dimension-value filtering is a follow-up.
"""

import xml.etree.ElementTree as ET


def list_accounts(client):
    root = client.post("exportAccounts", [
        ET.Element("include", {
            "attributes": "false",
            "dimensions": "false",
        }),
    ])
    return _flatten_metadata(root, ("account",))


def list_levels(client):
    root = client.post("exportLevels", [
        ET.Element("include", {"displayNameEnabled": "true"}),
    ])
    return _flatten_metadata(root, ("level",))


def list_dimensions(client):
    root = client.post("exportDimensions", [
        ET.Element("include", {
            "attributes": "false",
            "dimensionValues": "false",
            "displayNameEnabled": "true",
        }),
    ])
    return _flatten_metadata(root, ("dimension",))


def _flatten_metadata(root, tags):
    out = []
    for el in root.iter():
        if el.tag not in tags:
            continue
        code = el.get("code")
        name = el.get("name") or code
        if not code:
            continue
        out.append({
            "id": el.get("id") or "",
            "code": code,
            "name": name,
        })
    seen = set()
    deduped = []
    for item in out:
        key = (item["code"], item["id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    deduped.sort(key=lambda i: i["name"].lower())
    return deduped

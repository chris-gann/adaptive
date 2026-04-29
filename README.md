# Workday Adaptive Planning plugin for Dataiku DSS

Two-way connector for [Workday Adaptive Planning](https://www.workday.com/en-us/products/adaptive-planning/overview.html):

- **Import Adaptive Sheet** — a custom Python dataset that reads rows from a sheet (modeled, cube, standard, or transaction) into Dataiku.
- **Export Adaptive Sheet** — a custom Python exporter that pushes a Dataiku dataset back into a modeled, cube, or standard Adaptive sheet.
- **Adaptive Planning credentials** — a parameter set (preset) so admins configure the API connection once and every dataset/exporter reuses it.

## Setup

1. Install the plugin into DSS (*Plugins → Add plugin → Develop → From local folder*).
2. Go to *Plugin → Settings → Adaptive Planning credentials* and create a preset:
   - **Instance code** — your Adaptive instance code (the part after `@` in your Adaptive login).
   - **Username / Password** — credentials for an Adaptive API user.
   - **API version** — defaults to `v40`.
   - **API base URL** — defaults to `https://api.adaptiveplanning.com/api`. Override only for regional or sandbox endpoints.

## Importing a sheet

1. *Datasets → New dataset → Plugins → Workday Adaptive Planning → Import Adaptive Sheet*.
2. Pick the credentials preset. Once it is set, the **Sheet** dropdown loads every sheet in your instance, grouped by type (Modeled / Cube / Standard / Transaction).
3. Optionally set an Adaptive **version** (leave blank for the current working version).
4. *Test & get schema* fetches the column definitions; *Preview* runs the import.

## Exporting to a sheet

1. From any dataset, *Export → Adaptive — Export Sheet*.
2. Pick the credentials preset and target sheet, then choose:
   - **Write mode** — `REPLACE` clears existing rows first (modeled sheets only); `APPEND` adds to them.
   - **Batch size** — rows per Adaptive API call (default 5000). Lower this if Adaptive returns payload-size errors.
   - **Dry run** — validate and log batches without pushing.

The Dataiku schema must line up with the Adaptive sheet columns: column names need to match the column codes (or names) returned by `exportSheetDefinition`.

## API used under the hood

Workday's "Adaptive Planning API" comes in two flavors. The JSON variant covers a small subset of administrative resources; the **XML-payload-over-HTTPS-POST API** is the one with full sheet I/O coverage (`exportSheets`, `exportConfigurableModelData`, `importConfigurableModelData`, `importCubeData`, `importStandardData`, etc.). This plugin uses the XML API. All XML construction lives in `python-lib/adaptivetest/` and is hidden from the connector / exporter code.

## Layout

```
plugin.json
README.md
parameter-sets/adaptive-credentials/   # credentials preset
resource/compute_sheet_choices.py      # dynamic sheet dropdown
python-connectors/adaptive-test_import-sheet/   # import dataset
python-exporters/export-sheet/                  # export exporter
python-lib/adaptivetest/                        # shared client + sheet I/O
```

## Known limitations

- **Transaction sheets** are read-only. The XML API does not expose a generic transaction-import endpoint.
- **Cube and standard imports** follow Adaptive's additive merge semantics; the `Write mode` field only applies to modeled sheets.
- The import uses the configured **version** verbatim — there is no fuzzy matching on version names.
- Schema mismatches between the Dataiku dataset and the target Adaptive sheet are reported by Adaptive at import time; the exporter does not pre-validate them locally.

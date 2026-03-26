---
name: tdsx-describe-fields
description: Add human-readable field descriptions to Tableau .tdsx packaged datasource files. Supports downloading from Tableau Server, data sampling for smarter descriptions, and publishing back. Only use when the user explicitly attaches or references this skill.
---

# TDSX Field Description Skill

Four-phase workflow for adding field descriptions to a Tableau `.tdsx` datasource file. Supports two input modes:

- **Server mode** -- user provides a `datasource_name` and `project_name`. The agent downloads the `.tdsx` from Tableau Server.
- **Local mode** -- user provides a path to a local `.tdsx` file. Phase 0 is skipped.

Phase 3 (Publish) is **always offered as a user choice** at the end, regardless of the initial mode.

## Determine mode

If the user provided a **datasource name and project name**, use server mode (start at Phase 0).
If the user provided a **file path ending in `.tdsx`**, use local mode (skip to Phase 1).

---

## Phase 0 -- Download from Server (server mode only)

```
- [ ] Run download_datasource.py
- [ ] Capture downloaded .tdsx path
```

**Step 1: Download**

```bash
python <skill_dir>/scripts/download_datasource.py "<datasource_name>" "<project_name>"
```

Optional: specify `--output-dir <dir>` to control where the file is saved (default: CWD).

The script prints the absolute path of the downloaded `.tdsx` to stdout. Capture this as `<path_to_tdsx>` for all subsequent steps.

Requires environment variables (see Notes below).

---

## Phase 1 -- Extract, Sample, and Draft

```
- [ ] Run extract_fields.py
- [ ] Run sample_data.py
- [ ] Read field_metadata.json and data_sample.csv
- [ ] Fill in field_descriptions.json with initial descriptions
- [ ] Present JSON to user and STOP
```

**Step 1: Extract fields**

```bash
python <skill_dir>/scripts/extract_fields.py <path_to_tdsx>
```

This creates two files in the current working directory:
- `field_descriptions.json` -- `{"field_name": ""}` map to fill in
- `field_metadata.json` -- rich metadata (caption, datatype, role, calculation formula)

**Step 2: Sample data**

```bash
python <skill_dir>/scripts/sample_data.py <path_to_tdsx>
```

Optional: `--rows 500` (default is 500).

This creates `data_sample.csv` in the current working directory and prints column-level summary statistics to stdout.

If the `.tdsx` has no `.hyper` extract inside (e.g. a live connection), this step will fail. In that case, skip it and rely on metadata only for drafting descriptions.

**Step 3: Draft descriptions**

Read `field_metadata.json` to understand each field. Then read `data_sample.csv` (and the stdout summary) to see actual data values. Edit `field_descriptions.json`, filling in a concise description for every field based on:
- The field name and caption (e.g., `Revenue_EUR` -> revenue in Euros)
- The data type and role (measure vs dimension)
- Calculation formulas (for calculated fields, describe what the formula computes)
- Actual data values from the sample (e.g., seeing country codes helps describe a country dimension)

Keep descriptions short (one sentence). These are initial drafts for the user to refine.

**Step 4: Present and wait**

Tell the user that `field_descriptions.json` is ready for review. Show the JSON contents.
**STOP and wait for user approval before proceeding to Phase 2.**

---

## Phase 2 -- Inject and Repackage

Only proceed after the user approves (they may have edited the JSON).

```
- [ ] Run inject_descriptions.py
- [ ] Confirm outputs created
```

**Step 1: Inject**

```bash
python <skill_dir>/scripts/inject_descriptions.py <path_to_tdsx>
```

If the user placed the JSON elsewhere:

```bash
python <skill_dir>/scripts/inject_descriptions.py <path_to_tdsx> --descriptions <json_path>
```

**Step 2: Confirm**

Two output files are created next to the original `.tdsx`:
- `<name>_with_descriptions.tdsx` -- repackaged datasource ready to publish
- `<name>_with_descriptions.tds` -- standalone TDS for local Tableau Desktop testing

---

## Phase 3 -- Publish to Server (always offered)

After Phase 2, **always ask the user**: "Would you like to publish the datasource to Tableau Server?"

If the user declines, the workflow is done (local files are ready).

If the user accepts:

```
- [ ] Collect datasource_name and project_name (if not already known from Phase 0)
- [ ] Run publish_datasource.py
- [ ] Handle overwrite prompt if needed
- [ ] Confirm publication
```

**Step 1: Collect info**

If Phase 0 was used, `datasource_name` and `project_name` are already known.
If the user started in local mode, ask them for the `datasource_name` and `project_name` now.

**Step 2: Publish**

```bash
python <skill_dir>/scripts/publish_datasource.py "<path_to_with_descriptions_tdsx>" "<datasource_name>" "<project_name>"
```

The script publishes the datasource as `Verified <datasource_name>` to the specified project.

**Step 3: Handle existing datasource**

If exit code is **2**, a datasource named `Verified <datasource_name>` already exists.
Inform the user and ask for confirmation to overwrite. If approved, re-run with `--overwrite`:

```bash
python <skill_dir>/scripts/publish_datasource.py "<path_to_with_descriptions_tdsx>" "<datasource_name>" "<project_name>" --overwrite
```

**Step 4: Confirm**

Print the published datasource name and ID as confirmation.

---

## Notes

- Fields with empty descriptions in the JSON are skipped (no `<desc>` tag added).
- Parameters are automatically excluded from extraction.
- Calculated fields include their formula in `field_metadata.json` to help write better descriptions.
- Font styling is hardcoded: `fontcolor='#3c4043' fontname='Inter' fontsize='11'`.
- `data_sample.csv` is a working file; it can be deleted after the skill completes.

### Required environment variables (for server interactions)

| Variable | Required | Default | Description |
|---|---|---|---|
| `TABLEAU_SERVER_URL` | Yes | -- | Server URL (e.g. `https://reports.etorocorp.com/`) |
| `TABLEAU_TOKEN_NAME` | Yes | -- | Personal Access Token name |
| `TABLEAU_TOKEN_SECRET` | Yes | -- | Personal Access Token secret |
| `TABLEAU_SITE_NAME` | No | `''` | Tableau site name (empty string for default site) |
| `TABLEAU_API_VERSION` | No | `3.7` | REST API version |

### Dependencies

- `extract_fields.py` and `inject_descriptions.py` use only Python stdlib.
- `download_datasource.py` and `publish_datasource.py` require `tableauserverclient`.
- `sample_data.py` requires `pandas` and `pantab`.

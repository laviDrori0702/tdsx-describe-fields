---
name: tdsx-describe-fields
description: Add human-readable field descriptions to a datasource published on Tableau Server -- downloads the .tdsx, samples the live data via VizQL Data Service to draft descriptions, injects them, and publishes back. Optionally also drafts a datasource-level description (grain, coverage, aggregation rules, gotchas) for an AI agent that reads the datasource. Only use when the user explicitly attaches or references this skill.
---

# TDSX Field Description Skill

Four-phase workflow for adding field descriptions to a datasource **published on Tableau
Server**. The only input is a `datasource_name` and a `project_name` -- ask for both if the
user hasn't given them. Local `.tdsx` files are not supported: the workflow samples the live
datasource over VDS and publishes the result back, both of which need the server.

Phase 3 (Publish) is **always offered as a user choice** at the end, and it opens with an
**optional datasource-level description** add-on (opt-in, see Phase 3).

---

## Phase 0 -- Download from Server

```
- [ ] Run download_datasource.py --no-extract
- [ ] Capture downloaded .tdsx path
```

**Step 1: Download (metadata only)**

```bash
python <skill_dir>/scripts/download_datasource.py "<datasource_name>" "<project_name>" --no-extract
```

Optional: specify `--output-dir <dir>` to control where the file is saved (default: CWD).

`--no-extract` skips the `.hyper` data, which is much faster for large extracts. This download is only good for drafting descriptions (Phase 1) -- it is **not** sufficient for repackaging/publishing. Do not drop the flag here; the same download step is re-run later, without the flag, only if the user proceeds to Phase 2.

The script prints the absolute path of the downloaded `.tdsx` to stdout. Capture this as `<path_to_tdsx>` for all subsequent steps.

Requires environment variables (see Notes below).

---

## Phase 1 -- Extract, Sample, and Draft

```
- [ ] Run extract_fields.py
- [ ] Run extract_sql.py
- [ ] Run sample_via_vds.py --out vds_summary.txt and read its stdout summary
- [ ] Read field_metadata.json and the sampling summary
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

**Step 2: Extract the source query**

```bash
python <skill_dir>/scripts/extract_sql.py <path_to_tdsx>
```

Writes `custom_sql.sql` to the CWD: every `<relation type='text'>` body, deduplicated
(Tableau stores the same query once per connection, so a live + extract datasource
holds it twice). If the datasource has no custom SQL, the script falls back to
writing its physical table and join structure instead, fully commented out.

This file is a drafting input for both field descriptions and -- if the user opts in --
the datasource description in Phase 3.

**Step 3: Sample data**

Query the live datasource directly via VDS -- no extract download needed at all.

```bash
python <skill_dir>/scripts/sample_via_vds.py "<datasource_name>" "<project_name>" --out vds_summary.txt
```

Optional: `--rows 500` (default is 500). Requires the datasource's **API Access**
capability enabled (Tableau Server 2025.1+ or Tableau Cloud). The script prints a
column-level summary to stdout -- non-null counts, unique counts, sample values, and
min/max for numeric columns -- computed over the sampled rows.

Always pass `--out vds_summary.txt`: it writes the same summary to disk, prefixed with
the datasource's **existing server-side description**. Phase 3 reads that file, so the
summary survives context compaction and no second VDS query is needed.

If VDS fails (capability off, or an older server), say so and draft from
`field_metadata.json` and `custom_sql.sql` alone -- do not fall back to downloading
the extract.

**Step 4: Draft descriptions**

Read `field_metadata.json` to understand each field. Then use the sampling summary from Step 3 to see actual data values. Edit `field_descriptions.json`, filling in a concise description for every field based on:
- The field name and caption (e.g., `Revenue_EUR` -> revenue in Euros)
- The data type and role (measure vs dimension)
- Calculation formulas (for calculated fields, describe what the formula computes)
- Actual data values from the sampling summary (e.g., seeing country codes helps describe a country dimension)

Keep descriptions short (one sentence). These are initial drafts for the user to refine.

**Step 5: Present and wait**

Tell the user that `field_descriptions.json` is ready for review. Show the JSON contents.
**STOP and wait for user approval before proceeding to Phase 2.**

---

## Phase 2 -- Inject and Repackage

Only proceed after the user approves (they may have edited the JSON).

```
- [ ] Re-run download_datasource.py WITHOUT --no-extract
- [ ] Run inject_descriptions.py
- [ ] Confirm outputs created
```

**Step 0: Re-download with the extract**

The Phase 0 download skipped the `.hyper` extract for speed. Publishing (Phase 3) always uploads a complete package, so re-run the same command without `--no-extract` now, before repackaging:

```bash
python <skill_dir>/scripts/download_datasource.py "<datasource_name>" "<project_name>"
```

This overwrites `<path_to_tdsx>` in place with the full package (data included).

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

## Phase 3 -- Datasource Description (optional) + Publish

Phase 3 asks the user **two separate questions**, in this order.

### Question 1 -- Datasource description (opt-in)

Ask: *"Would you like to add a datasource-level description? It is written for the AI
agent that answers questions inside the dashboards."*

If the user declines, skip straight to Question 2.

A datasource description is **server-side metadata only** -- there is no place for it
in the `.tds`, so it can only be set by publishing. If the user wants a description but
then declines to publish, say so plainly: the drafted file stays on disk unused.

```
- [ ] Read custom_sql.sql, vds_summary.txt, and the approved field_descriptions.json
- [ ] Read CONTEXT.md / CLAUDE.md / docs/adr/ if they exist in the CWD
- [ ] Write datasource_description.txt using the template below
- [ ] Show it inline, take edits, STOP until approved
```

**Who reads this.** An AI agent embedded in the dashboards reads the datasource
description *and* the field descriptions to answer user questions. So the datasource
description must be **strictly non-overlapping** with the field descriptions: it carries
only the cross-field truths that no single field's description can state. Never restate
what a field description already says.

**Drafting inputs**, in order of authority:

1. `custom_sql.sql` -- source tables, joins, `WHERE` filters, `GROUP BY` grain.
2. `vds_summary.txt` -- date min/max for coverage, unique counts for grain, plus the
   existing server-side description at the top (**seed from it**: it holds jargon the
   skill cannot invent, so preserve its terminology rather than replacing it).
3. The user-approved `field_descriptions.json` -- inherits whatever jargon the user
   settled on during Phase 1.
4. `CONTEXT.md`, `CLAUDE.md`, `docs/adr/` **if present in the CWD** -- the jargon source
   for the `Glossary:` line. Skip the section silently when none exist.
5. SQL comments and CTE names -- a thin but always-available jargon source.

**Format:** labeled lines, one `Label: value` per line. Soft budget ~1500 characters.

| Line | Include |
|---|---|
| `Purpose:` | always |
| `Grain:` -- what exactly one row represents | always |
| `Coverage:` -- date range and freshness lag | always |
| `Aggregation:` -- which measures are point-in-time stocks vs additive flows | always |
| `Scope:` -- filters and exclusions baked into the SQL | always |
| `Metrics:` -- canonical formulas the agent must not reinvent | when derivable |
| `Glossary:` -- `term = meaning`, semicolon-separated | when a jargon source exists |
| `Gotchas:` -- traps a correct-looking query falls into | when derivable |

Example:

```
Purpose: Daily snapshots of B2B subscription contracts for lifecycle dashboards.
Grain: One row per contract per norm_date.
Coverage: 2025-01-01 to current date; usable max date is MAX(norm_date) - 2.
Aggregation: num_contracts is a point-in-time stock -- do NOT sum across dates;
  total_in and total_out are additive flows.
Scope: Excludes cancelled subscriptions; contracts starting before 2024-01-01 are out of range.
Metrics: total_in = new_business + upgrades_downgrades + in_trial + other_in.
Glossary: norm_date = the date-spine day a snapshot belongs to; ROW = all countries
  outside USA and India.
Gotchas: end_date is inclusive -- a contract ending on day D still counts on D but
  leaves the stock on D+1.
```

**Grounding rule.** `Grain`, `Aggregation` and `Scope` are *inferred* from the SQL, and
inference can be wrong. Prefix any line **not directly derivable** from the inputs with
`?? ` so the review shows the user exactly what to check:

```
?? Grain: One row per contract per norm_date.
```

`publish_datasource.py` **refuses to publish** (exit 3) while any `??` remains, so every
marker must be resolved or removed during review. Never strip a marker yourself just to
get the publish through -- take it to the user.

Write the draft to `datasource_description.txt`, show it inline, and **STOP for approval**.
The user may edit the file directly; re-read it after they say they have.

### Question 2 -- Publish

**Always ask**: "Would you like to publish the datasource to Tableau Server?"

If the user declines, the workflow is done (local files are ready).

If the user accepts:

```
- [ ] Run publish_datasource.py
- [ ] Handle overwrite prompt if needed
- [ ] Confirm publication
```

**Step 1: Publish**

`datasource_name` and `project_name` are already known from Phase 0.

```bash
python <skill_dir>/scripts/publish_datasource.py "<path_to_with_descriptions_tdsx>" "<datasource_name>" "<project_name>"
```

If the user approved a datasource description, add `--description-file`:

```bash
python <skill_dir>/scripts/publish_datasource.py "<path_to_with_descriptions_tdsx>" "<datasource_name>" "<project_name>" --description-file datasource_description.txt
```

The script publishes the datasource as `Verified <datasource_name>` to the specified project.
With `--description-file` it also re-reads the published datasource and warns if the server
truncated the description (Tableau's cap is undocumented).

**Exit code 3** means the description file still has `??` markers -- nothing was published.
Resolve them with the user and re-run.

**Step 2: Handle existing datasource**

If exit code is **2**, a datasource named `Verified <datasource_name>` already exists.
Inform the user and ask for confirmation to overwrite. If approved, re-run with `--overwrite`:

```bash
python <skill_dir>/scripts/publish_datasource.py "<path_to_with_descriptions_tdsx>" "<datasource_name>" "<project_name>" --overwrite
```

Keep `--description-file` on the retry if it was on the first attempt -- dropping it
publishes with no description.

**Step 3: Confirm**

Print the published datasource name and ID as confirmation.

**Step 4: Tell the user to re-embed the database credentials**

The published datasource does **not** carry the database password -- Tableau never
returns the stored credential on download, so the repackaged `.tdsx` uploads a
connection with no password. Nothing fails at publish time; the next **scheduled
extract refresh** fails authentication, and the stale extract keeps serving data,
so the breakage is easy to miss.

After a successful publish, always end by instructing the user:

> Open the published datasource in Tableau Cloud/Server -> **... -> Edit Connection**,
> enter the database username and password, tick **Embed password**, save, then run
> **Refresh Extracts** once to verify it succeeds.

Do not report the workflow as complete without this message.

---

## Notes

- Fields with empty descriptions in the JSON are skipped (no `<desc>` tag added).
- Parameters are automatically excluded from extraction.
- Calculated fields include their formula in `field_metadata.json` to help write better descriptions.
- Font styling is hardcoded: `fontcolor='#3c4043' fontname='Inter' fontsize='11'`.
- The extract can't be skipped for publish, even when overwriting the same datasource in place: Tableau's Publish Data Source call is always a full-content replace, not a metadata patch, regardless of the `overwrite` flag. The only endpoint that updates without the extract (Update Data Source) can only touch owner/project/certification, never columns or descriptions.
- The datasource-level description lives **only** on the server (`DatasourceItem.description`).
  Unlike field descriptions there is no `<desc>` for it in the `.tds`, which is why it rides
  along with the publish call instead of being injected in Phase 2.
- Tableau stores custom SQL once per connection, so a live + extract datasource holds the
  same query twice; `extract_sql.py` deduplicates identical bodies.
- `sample_via_vds.py` reuses the same TSC sign-in session as `download_datasource.py` (via `find_datasource` in `_shared.py`) and calls the VizQL Data Service REST endpoints directly with `requests` (a transitive dependency of `tableauserverclient`, already installed) -- no new dependency, no pandas/pantab anywhere in the skill.

### Required environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TABLEAU_SERVER_URL` | Yes | -- | Server URL (e.g. `https://reports.etorocorp.com/`) |
| `TABLEAU_TOKEN_NAME` | Yes | -- | Personal Access Token name |
| `TABLEAU_TOKEN_SECRET` | Yes | -- | Personal Access Token secret |
| `TABLEAU_SITE_NAME` | No | `''` | Tableau site name (empty string for default site) |
| `TABLEAU_API_VERSION` | No | `3.7` | REST API version |

### Dependencies

- `extract_fields.py`, `extract_sql.py` and `inject_descriptions.py` use only Python stdlib.
- `download_datasource.py`, `publish_datasource.py` and `sample_via_vds.py` require `tableauserverclient`.

# tdsx-describe-fields

A Claude Code skill that adds human-readable field descriptions to a Tableau datasource
published on Server or Cloud — downloads the `.tdsx`, drafts descriptions from field
metadata plus a live data sample, injects them into the datasource XML, and publishes back.

Field descriptions are what users see in the Data pane tooltip in Tableau Desktop and
Web Edit. Writing them by hand for a 60-field datasource is tedious; this skill drafts
them all, then hands them to you for review before anything is written or published.

It can optionally also draft a **datasource-level description** (see
[Datasource description](#datasource-description-optional)) — a short structured summary
of grain, coverage, aggregation rules and gotchas, aimed at an AI agent reading the
datasource to answer questions about a dashboard.

## Requirements

Python 3.10+ (the scripts use `str | None` annotations) and, for the four scripts that
talk to the server, `tableauserverclient`:

```bash
pip install tableauserverclient
```

## Install

Clone into your Claude Code skills directory:

```bash
git clone https://github.com/laviDrori0702/tdsx-describe-fields.git \
  ~/.claude/skills/tdsx-describe-fields
```

Then reference it in a prompt: `use the tdsx-describe-fields skill on ...`.
The skill is opt-in — it only activates when explicitly requested.

## Usage

Give a datasource name and a project name:

> `use tdsx-describe-fields on the "Sales Extract" datasource in the "Finance" project`

The datasource has to be **published on Tableau Server or Cloud** — a local `.tdsx` won't
work, since the skill samples the live datasource over VDS and publishes the result back.

The workflow always **stops for your approval** after drafting descriptions, and always
**asks before publishing**.

## Workflow

| Phase | What happens | Output |
|---|---|---|
| 0 — Download | Fetch the `.tdsx` from Server, metadata only (`--no-extract`, fast) | `<name>.tdsx` |
| 1 — Extract & draft | List fields, dump the source query, sample real data via VDS, draft one-line descriptions | `field_descriptions.json`, `field_metadata.json`, `custom_sql.sql`, `vds_summary.txt` |
| **review** | You edit `field_descriptions.json`. Nothing proceeds until you approve. | |
| 2 — Inject | Re-download with the extract, write `<desc>` tags into the datasource XML | `<name>_with_descriptions.tdsx` + `.tds` |
| 3a — Describe | Optional, opt-in. Drafts a datasource-level description for review | `datasource_description.txt` |
| 3b — Publish | Optional. Publishes as `Verified <name>` to the chosen project | published datasource |

Data sampling goes through **VizQL Data Service** against the live datasource — no
extract is ever downloaded for it. The agent reads the column summary — non-null and
unique counts, sample values, numeric min/max — and drafts from that. With `--out` the
summary is also saved to disk for phase 3 to reuse. If VDS isn't available, drafting
falls back to field metadata and the source query alone.

## Datasource description (optional)

Field descriptions describe one column each. A **datasource description** carries what no
single field can: what one row means, which measures are safe to sum, what the SQL already
filters out. That is exactly what an AI agent sitting inside a dashboard needs in order to
answer questions without double-counting a snapshot or claiming coverage the data lacks.

It's **opt-in** and asked for at phase 3, because a good one carries company jargon the
skill can't invent. When you decline, nothing changes and the workflow proceeds straight
to publishing.

The draft is written as labeled lines to `datasource_description.txt`:

```
Purpose: Daily snapshots of B2B subscription contracts for lifecycle dashboards.
Grain: One row per contract per norm_date.
Coverage: 2025-01-01 to current date; usable max date is MAX(norm_date) - 2.
Aggregation: num_contracts is a point-in-time stock -- do NOT sum across dates;
  total_in and total_out are additive flows.
Scope: Excludes cancelled subscriptions; contracts before 2024-01-01 are out of range.
Metrics: total_in = new_business + upgrades_downgrades + in_trial + other_in.
Glossary: norm_date = the date-spine day a snapshot belongs to; ROW = all countries outside USA and India.
Gotchas: end_date is inclusive -- a contract ending on day D still counts on D.
```

It's drafted from the source query (`custom_sql.sql`), the data sample
(`vds_summary.txt`), your approved field descriptions, the datasource's existing
server-side description, and — if they happen to exist in the working directory — repo
docs like `CONTEXT.md` or `docs/adr/` as a jargon source for the `Glossary:` line.
The whole thing targets ~1500 characters.

You review and edit it exactly like the field descriptions; nothing publishes until you
approve. Lines the agent *inferred* rather than read are prefixed `?? ` so you know what
to check, and `publish_datasource.py` **refuses to publish** (exit `3`) while any `??`
remains.

Two things to know: the description lives **only on the server** — there's no place for
it in the `.tds` — so it's set by the publish call, and declining to publish discards it.
And Tableau's length cap is undocumented, so the script re-reads the published datasource
and warns if the server truncated what it sent.

## Scripts

| Script | Purpose | Deps |
|---|---|---|
| `download_datasource.py <name> <project> [--output-dir DIR] [--no-extract]` | Download a `.tdsx` from Server | `tableauserverclient` |
| `extract_fields.py <tdsx>` | Emit `field_descriptions.json` + `field_metadata.json` | stdlib |
| `extract_sql.py <tdsx> [--out FILE]` | Dump the custom SQL (deduplicated), or the table/join structure | stdlib |
| `sample_via_vds.py <name> <project> [--rows N] [--out FILE]` | Sample the live datasource via VDS (default 500 rows), print a column summary | `tableauserverclient` |
| `inject_descriptions.py <tdsx> [--descriptions JSON]` | Write descriptions, repackage | stdlib |
| `publish_datasource.py <tdsx> <name> <project> [--overwrite] [--description-file FILE]` | Publish to Server (exit `2` = name already exists, exit `3` = unreviewed `??` markers) | `tableauserverclient` |

Each runs standalone, outside the skill, if you want just one step.

## Environment variables

Required — every phase talks to the server.

| Variable | Required | Default | Description |
|---|---|---|---|
| `TABLEAU_SERVER_URL` | Yes | — | e.g. `https://your-server.example.com/` |
| `TABLEAU_TOKEN_NAME` | Yes | — | Personal Access Token name |
| `TABLEAU_TOKEN_SECRET` | Yes | — | Personal Access Token secret |
| `TABLEAU_SITE_NAME` | No | `''` | Site name (empty for the default site) |
| `TABLEAU_API_VERSION` | No | `3.7` | REST API version |

## Gotchas

- **Re-embed the database password after publishing.** Tableau never returns a stored
  credential on download, so the repackaged `.tdsx` publishes with no password. Nothing
  fails at publish time — the next *scheduled extract refresh* fails auth while the
  stale extract keeps serving data, so it's easy to miss. Fix: **… → Edit Connection**,
  enter the credentials, tick **Embed password**, then run **Refresh Extracts** once.
- **The extract can't be skipped for publish**, even when overwriting in place. Tableau's
  Publish Data Source call is a full-content replace; the metadata-only *Update Data
  Source* endpoint can't touch columns or descriptions.
- **VDS sampling needs API Access** enabled on the datasource (Tableau Server 2025.1+ or
  Cloud). Without it there's no sampling at all — drafting falls back to field metadata.
- **A datasource description can't be set without publishing.** It's server-side
  metadata with no `.tds` equivalent, so declining to publish discards the drafted text.
- **Custom SQL is stored once per connection.** A live + extract datasource holds the
  same query twice; `extract_sql.py` deduplicates identical bodies so a 200-line query
  isn't dumped twice.
- Fields with an empty string in `field_descriptions.json` are skipped — no tag written.
- Parameters are excluded from extraction.
- Font styling on injected descriptions is hardcoded (`Inter`, 11pt, `#3c4043`).

## Tests

```bash
python -m pytest tests/
```

Covers the two pieces with real branching: `extract_sql.py`'s relation parsing (duplicate
SQL, distinct queries, table-only fallback) and the `??` marker guard that gates
publishing.

## License

MIT

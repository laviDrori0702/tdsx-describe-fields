# tdsx-describe-fields

A Claude Code skill that adds human-readable field descriptions to a Tableau datasource
published on Server or Cloud — downloads the `.tdsx`, drafts descriptions from field
metadata plus a live data sample, injects them into the datasource XML, and publishes back.

Field descriptions are what users see in the Data pane tooltip in Tableau Desktop and
Web Edit. Writing them by hand for a 60-field datasource is tedious; this skill drafts
them all, then hands them to you for review before anything is written or published.

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
| 1 — Extract & draft | List fields, sample real data via VDS, draft one-line descriptions | `field_descriptions.json`, `field_metadata.json` |
| **review** | You edit `field_descriptions.json`. Nothing proceeds until you approve. | |
| 2 — Inject | Re-download with the extract, write `<desc>` tags into the datasource XML | `<name>_with_descriptions.tdsx` + `.tds` |
| 3 — Publish | Optional. Publishes as `Verified <name>` to the chosen project | published datasource |

Data sampling goes through **VizQL Data Service** against the live datasource — no
extract is ever downloaded for it, and nothing is written to disk. The agent reads the
column summary off stdout — non-null and unique counts, sample values, numeric min/max —
and drafts from that. If VDS isn't available, drafting falls back to field metadata alone.

## Scripts

| Script | Purpose | Deps |
|---|---|---|
| `download_datasource.py <name> <project> [--output-dir DIR] [--no-extract]` | Download a `.tdsx` from Server | `tableauserverclient` |
| `extract_fields.py <tdsx>` | Emit `field_descriptions.json` + `field_metadata.json` | stdlib |
| `sample_via_vds.py <name> <project> [--rows N]` | Sample the live datasource via VDS, print a column summary | `tableauserverclient` |
| `inject_descriptions.py <tdsx> [--descriptions JSON]` | Write descriptions, repackage | stdlib |
| `publish_datasource.py <tdsx> <name> <project> [--overwrite]` | Publish to Server (exit code `2` = name already exists) | `tableauserverclient` |

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
- Fields with an empty string in `field_descriptions.json` are skipped — no tag written.
- Parameters are excluded from extraction.
- Font styling on injected descriptions is hardcoded (`Inter`, 11pt, `#3c4043`).

## License

MIT

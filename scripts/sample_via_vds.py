"""Sample a published datasource's data via Tableau's VizQL Data Service (VDS).

Usage: python sample_via_vds.py <datasource_name> <project_name> [--rows 500]

Server-mode replacement for sample_data.py: queries the live datasource on
Tableau Server directly, so no .hyper extract ever needs to be downloaded for
drafting field descriptions. Requires the datasource's "API Access"
capability to be enabled (Tableau Server 2025.1+ or Tableau Cloud).

Outputs (in current working directory):
  - data_sample.csv  : sample of rows pulled via VDS query-datasource

Also prints column-level summary statistics to stdout, computed over the
sample only (VDS does not expose a full-population read).
"""

import argparse
import csv
import sys
from pathlib import Path

from _shared import connect_to_server, find_datasource, get_server_env


def vds_request(server, path: str, payload: dict) -> dict:
    """POST a JSON body to a VDS endpoint using the already-authenticated session.

    Args:
        server: Authenticated TSC.Server instance (reused for auth token + SSL options).
        path: VDS endpoint name, e.g. 'read-metadata' or 'query-datasource'.
        payload: The JSON request body.

    Returns:
        The decoded JSON response body.
    """
    url = f"{server.server_address.rstrip('/')}/api/v1/vizql-data-service/{path}"
    headers = {
        "X-Tableau-Auth": server.auth_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = server.session.post(url, json=payload, headers=headers,
                                   **server.http_options)
    if not response.ok:
        print(f"Error: VDS {path} returned HTTP {response.status_code}: "
              f"{response.text.strip()[:500] or '(no body)'}", file=sys.stderr)
        if response.status_code in (400, 404):
            print("  This usually means the datasource's 'API Access' capability "
                  "is disabled, or the server is older than 2025.1.", file=sys.stderr)
        sys.exit(1)
    return response.json()


def read_metadata(server, luid: str) -> list[dict]:
    """Fetch queryable fields for a datasource via VDS read-metadata.

    Args:
        server: Authenticated TSC.Server instance.
        luid: The datasource's LUID.

    Returns:
        List of {fieldCaption, dataType} dicts, one per queryable field.
    """
    body = vds_request(server, "read-metadata",
                       {"datasource": {"datasourceLuid": luid}})
    fields = [
        {"caption": f.get("fieldCaption", ""), "dataType": f.get("dataType", "")}
        for f in body.get("data", []) if f.get("fieldCaption")
    ]
    if not fields:
        print("Error: VDS read-metadata returned no queryable fields. "
              "Enable 'API Access' on the datasource and re-run.", file=sys.stderr)
        sys.exit(1)
    return fields


def query_rows(server, luid: str, captions: list[str], row_limit: int) -> list[dict]:
    """Fetch a capped sample of rows via VDS query-datasource.

    Args:
        server: Authenticated TSC.Server instance.
        luid: The datasource's LUID.
        captions: Field captions to query (all queryable fields).
        row_limit: Maximum rows to return.

    Returns:
        Sampled rows as dicts keyed by field caption.
    """
    payload = {
        "datasource": {"datasourceLuid": luid},
        "query": {"fields": [{"fieldCaption": c} for c in captions]},
        "options": {"rowLimit": row_limit},
    }
    body = vds_request(server, "query-datasource", payload)
    rows = body.get("data", [])
    if not rows:
        print("Error: VDS query-datasource returned zero rows.", file=sys.stderr)
        sys.exit(1)
    return rows


def print_summary(rows: list[dict], captions: list[str]) -> None:
    """Print per-column summary stats (over the sample) to stdout.

    Args:
        rows: The sampled rows, keyed by field caption.
        captions: Field captions, in display order.
    """
    print("\n=== Column Summary (sample only) ===\n")
    for caption in captions:
        values = [row.get(caption) for row in rows if row.get(caption) is not None]
        unique = len(set(values))
        sample_str = ", ".join(str(v) for v in values[:5])

        print(f"  {caption}")
        print(f"    non-null: {len(values)}/{len(rows)}  |  unique: {unique}")
        print(f"    sample values: {sample_str}")

        numeric = [v for v in values if isinstance(v, (int, float))]
        if numeric:
            print(f"    min: {min(numeric)}  |  max: {max(numeric)}  |  "
                 f"mean: {sum(numeric) / len(numeric):.4f}")
        print()


def main() -> None:
    """Main entry point for VDS-based data sampling."""
    parser = argparse.ArgumentParser(
        description="Sample a published datasource's data via VDS."
    )
    parser.add_argument("datasource_name", help="Name of the datasource on the server")
    parser.add_argument("project_name", help="Project that hosts the datasource")
    parser.add_argument("--rows", type=int, default=500,
                        help="Number of rows to sample (default: 500)")
    args = parser.parse_args()

    server_url, token_name, token_secret, site_name, api_version = get_server_env()

    server = None
    try:
        server = connect_to_server(
            server_url, token_name, token_secret, site_name, api_version
        )
        ds = find_datasource(server, args.datasource_name, args.project_name)

        fields = read_metadata(server, ds.id)
        captions = [f["caption"] for f in fields]

        rows = query_rows(server, ds.id, captions, args.rows)

        csv_path = Path.cwd() / "data_sample.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=captions)
            writer.writeheader()
            writer.writerows(rows)

        print(f"Sampled {len(rows)} rows -> {csv_path}", file=sys.stderr)
        print_summary(rows, captions)
    finally:
        if server is not None:
            server.auth.sign_out()


if __name__ == "__main__":
    main()

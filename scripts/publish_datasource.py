"""Publish a .tdsx datasource to Tableau Server with a 'Verified' name prefix.

Usage:
  python publish_datasource.py <path_to_tdsx> <datasource_name> <project_name>
  python publish_datasource.py <path_to_tdsx> <datasource_name> <project_name> --overwrite
  python publish_datasource.py ... --description-file datasource_description.txt

Exit codes:
  0 - Published successfully
  1 - Error (missing env vars, file not found, etc.)
  2 - A 'Verified <name>' datasource already exists; re-run with --overwrite
      after user confirmation
  3 - The description file still contains unreviewed '??' markers; nothing
      was published

Requires the same environment variables as download_datasource.py.
"""

import argparse
import sys
from pathlib import Path

import tableauserverclient as TSC

from _shared import connect_to_server, get_server_env


# Prefix a drafting phase puts on any line it inferred rather than read from the
# source. Unreviewed markers must never reach the server: the in-dashboard agent
# treats this description as ground truth.
UNVERIFIED_MARKER = "??"

# Soft target for description length. Tableau's own cap is undocumented, so this
# is a drafting guideline only -- the real check is the post-publish read-back.
DESCRIPTION_SOFT_LIMIT = 1500


def load_description(description_path: Path) -> str:
    """Read the datasource description, rejecting unreviewed draft markers.

    Args:
        description_path: Path to the description text file.

    Returns:
        The description text, stripped of surrounding whitespace.

    Raises:
        SystemExit: Exit 1 if the file is missing or empty; exit 3 if any line
            still carries the unverified marker.
    """
    if not description_path.exists():
        print(f"Error: Description file not found: {description_path}",
              file=sys.stderr)
        sys.exit(1)

    text = description_path.read_text(encoding="utf-8").strip()
    if not text:
        print(f"Error: Description file is empty: {description_path}",
              file=sys.stderr)
        sys.exit(1)

    flagged = [line for line in text.splitlines()
               if line.lstrip().startswith(UNVERIFIED_MARKER)]
    if flagged:
        print(f"Error: {len(flagged)} line(s) in {description_path.name} still "
              f"carry the '{UNVERIFIED_MARKER}' unverified marker:",
              file=sys.stderr)
        for line in flagged:
            print(f"    {line}", file=sys.stderr)
        print("These lines were inferred, not read from the source. Review them "
              "with the user, remove the markers, and re-run.", file=sys.stderr)
        sys.exit(3)

    if len(text) > DESCRIPTION_SOFT_LIMIT:
        print(f"Note: description is {len(text)} chars (soft target is "
              f"{DESCRIPTION_SOFT_LIMIT}). Publishing anyway; the read-back "
              f"reports any server-side truncation.", file=sys.stderr)

    return text


def resolve_project_id(server: TSC.Server, project_name: str) -> str:
    """Resolve a project name to its server ID.

    Args:
        server: Authenticated TSC.Server instance.
        project_name: Name of the target project.

    Returns:
        The project ID string.
    """
    projects = list(server.projects.filter(name=project_name))
    if not projects:
        print(f"Error: Project '{project_name}' not found on server.",
              file=sys.stderr)
        sys.exit(1)
    project = projects[0]
    print(f"Resolved project: {project.name} (ID: {project.id})",
          file=sys.stderr)
    return project.id


def check_existing(server: TSC.Server, verified_name: str,
                   project_name: str) -> bool:
    """Check if a datasource with the verified name already exists.

    Args:
        server: Authenticated TSC.Server instance.
        verified_name: The 'Verified <name>' datasource name to check.
        project_name: Project to search in.

    Returns:
        True if the datasource already exists.
    """
    matches = list(server.datasources.filter(
        name=verified_name, project_name=project_name
    ))
    return len(matches) > 0


def publish(server: TSC.Server, tdsx_path: Path, verified_name: str,
            project_id: str, overwrite: bool,
            description: str | None = None) -> TSC.DatasourceItem:
    """Publish a .tdsx file to Tableau Server.

    Args:
        server: Authenticated TSC.Server instance.
        tdsx_path: Path to the .tdsx file to publish.
        verified_name: Name for the published datasource.
        project_id: Target project ID.
        overwrite: If True, overwrite existing datasource.
        description: Optional datasource-level description. It is server-side
            metadata only -- there is no place for it in the .tds -- so it has
            to ride along with the publish call.

    Returns:
        The published DatasourceItem.
    """
    ds_item = TSC.DatasourceItem(project_id=project_id, name=verified_name)
    if description:
        ds_item.description = description
    mode = (TSC.Server.PublishMode.Overwrite if overwrite
            else TSC.Server.PublishMode.CreateNew)
    new_ds = server.datasources.publish(ds_item, str(tdsx_path), mode)
    return new_ds


def verify_description(server: TSC.Server, datasource_id: str,
                       expected: str) -> None:
    """Re-read the published datasource and warn if the description was altered.

    Tableau's description length cap is undocumented, so truncation is detected
    empirically rather than guessed at.

    Args:
        server: Authenticated TSC.Server instance.
        datasource_id: LUID of the just-published datasource.
        expected: The description text that was sent.
    """
    stored = server.datasources.get_by_id(datasource_id).description or ""
    if stored.strip() == expected.strip():
        print(f"Description verified on server ({len(expected)} chars).")
        return

    print(f"WARNING: server stored {len(stored)} of {len(expected)} description "
          f"chars -- the description was truncated or rejected.",
          file=sys.stderr)


def main() -> None:
    """Main entry point for datasource publishing."""
    parser = argparse.ArgumentParser(
        description="Publish a .tdsx to Tableau Server with 'Verified' prefix."
    )
    parser.add_argument("tdsx_path",
                        help="Path to the .tdsx file to publish")
    parser.add_argument("datasource_name",
                        help="Original datasource name (prefix 'Verified' is added)")
    parser.add_argument("project_name",
                        help="Target project on the server")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite if 'Verified <name>' already exists")
    parser.add_argument("--description-file",
                        help="Path to a text file holding the datasource-level "
                             "description to set on publish")
    args = parser.parse_args()

    tdsx_path = Path(args.tdsx_path).resolve()
    if not tdsx_path.exists():
        print(f"Error: File not found: {tdsx_path}", file=sys.stderr)
        sys.exit(1)

    verified_name = f"Verified {args.datasource_name}"

    # Loaded before sign-in so a bad description file fails fast without
    # opening a server session.
    description = (load_description(Path(args.description_file).resolve())
                   if args.description_file else None)

    server_url, token_name, token_secret, site_name, api_version = get_server_env()

    # Connect inside try block so sign_out is always called on success
    server = None
    try:
        server = connect_to_server(
            server_url, token_name, token_secret, site_name, api_version
        )

        if not args.overwrite and check_existing(server, verified_name, args.project_name):
            print(
                f"WARNING: Datasource '{verified_name}' already exists in "
                f"project '{args.project_name}'.",
                file=sys.stderr,
            )
            print(
                "Re-run with --overwrite after user confirmation.",
                file=sys.stderr,
            )
            sys.exit(2)

        project_id = resolve_project_id(server, args.project_name)
        new_ds = publish(server, tdsx_path, verified_name, project_id,
                         args.overwrite, description)
        print(f"Published '{verified_name}' (ID: {new_ds.id}) "
              f"to project '{args.project_name}'")

        if description:
            verify_description(server, new_ds.id, description)
    finally:
        if server is not None:
            server.auth.sign_out()


if __name__ == "__main__":
    main()

"""Publish a .tdsx datasource to Tableau Server with a 'Verified' name prefix.

Usage:
  python publish_datasource.py <path_to_tdsx> <datasource_name> <project_name>
  python publish_datasource.py <path_to_tdsx> <datasource_name> <project_name> --overwrite

Exit codes:
  0 - Published successfully
  1 - Error (missing env vars, file not found, etc.)
  2 - A 'Verified <name>' datasource already exists; re-run with --overwrite
      after user confirmation

Requires the same environment variables as download_datasource.py.
"""

import argparse
import sys
from pathlib import Path

import tableauserverclient as TSC

from _shared import connect_to_server, get_server_env


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
            project_id: str, overwrite: bool) -> TSC.DatasourceItem:
    """Publish a .tdsx file to Tableau Server.

    Args:
        server: Authenticated TSC.Server instance.
        tdsx_path: Path to the .tdsx file to publish.
        verified_name: Name for the published datasource.
        project_id: Target project ID.
        overwrite: If True, overwrite existing datasource.

    Returns:
        The published DatasourceItem.
    """
    ds_item = TSC.DatasourceItem(project_id=project_id, name=verified_name)
    mode = (TSC.Server.PublishMode.Overwrite if overwrite
            else TSC.Server.PublishMode.CreateNew)
    new_ds = server.datasources.publish(ds_item, str(tdsx_path), mode)
    return new_ds


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
    args = parser.parse_args()

    tdsx_path = Path(args.tdsx_path).resolve()
    if not tdsx_path.exists():
        print(f"Error: File not found: {tdsx_path}", file=sys.stderr)
        sys.exit(1)

    verified_name = f"Verified {args.datasource_name}"

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
        new_ds = publish(server, tdsx_path, verified_name, project_id, args.overwrite)
        print(f"Published '{verified_name}' (ID: {new_ds.id}) "
              f"to project '{args.project_name}'")
    finally:
        if server is not None:
            server.auth.sign_out()


if __name__ == "__main__":
    main()

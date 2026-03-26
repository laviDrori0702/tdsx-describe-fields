"""Download a datasource from Tableau Server by name and project.

Usage: python download_datasource.py <datasource_name> <project_name> [--output-dir <dir>]

Requires environment variables:
  TABLEAU_SERVER_URL    - e.g. https://reports.etorocorp.com/
  TABLEAU_TOKEN_NAME    - Personal Access Token name
  TABLEAU_TOKEN_SECRET  - Personal Access Token secret
  TABLEAU_SITE_NAME     - Site name (optional, defaults to '')
  TABLEAU_API_VERSION   - API version (optional, defaults to '3.7')

Prints the absolute path of the downloaded .tdsx file to stdout on success.
"""

import argparse
import sys
from pathlib import Path

import tableauserverclient as TSC

from _shared import connect_to_server, get_server_env, sanitize_filename


def find_datasource(server: TSC.Server, datasource_name: str,
                    project_name: str) -> TSC.DatasourceItem:
    """Find a datasource on Tableau Server by name and project.

    Args:
        server: Authenticated TSC.Server instance.
        datasource_name: Name of the datasource to find.
        project_name: Project containing the datasource.

    Returns:
        The matching DatasourceItem.
    """
    matches = list(server.datasources.filter(
        name=datasource_name, project_name=project_name
    ))

    if len(matches) == 0:
        print(
            f"Error: No datasource '{datasource_name}' found in project '{project_name}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(matches) > 1:
        print(
            f"Warning: {len(matches)} datasources named '{datasource_name}' "
            f"in project '{project_name}'. Using the first match.",
            file=sys.stderr,
        )

    ds = matches[0]
    print(f"Found datasource: {ds.name} (ID: {ds.id}, project: {ds.project_name})",
          file=sys.stderr)
    return ds


def download(server: TSC.Server, datasource: TSC.DatasourceItem,
             output_dir: Path) -> str:
    """Download a datasource .tdsx file from Tableau Server.

    Args:
        server: Authenticated TSC.Server instance.
        datasource: The datasource to download.
        output_dir: Directory to save the downloaded file.

    Returns:
        Absolute path to the downloaded .tdsx file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize the datasource name for safe filesystem usage
    safe_name = sanitize_filename(datasource.name)
    filepath = output_dir / safe_name
    downloaded = server.datasources.download(datasource.id, filepath=str(filepath))
    return str(Path(downloaded).resolve())


def main() -> None:
    """Main entry point for datasource download."""
    parser = argparse.ArgumentParser(
        description="Download a datasource from Tableau Server."
    )
    parser.add_argument("datasource_name",
                        help="Name of the datasource on the server")
    parser.add_argument("project_name",
                        help="Project that hosts the datasource")
    parser.add_argument("--output-dir", default=".",
                        help="Directory to save the .tdsx (default: CWD)")
    args = parser.parse_args()

    server_url, token_name, token_secret, site_name, api_version = get_server_env()

    # Connect inside try block so sign_out is always called on success
    server = None
    try:
        server = connect_to_server(
            server_url, token_name, token_secret, site_name, api_version
        )
        ds = find_datasource(server, args.datasource_name, args.project_name)
        tdsx_path = download(server, ds, Path(args.output_dir))
        print(tdsx_path)
    finally:
        if server is not None:
            server.auth.sign_out()


if __name__ == "__main__":
    main()

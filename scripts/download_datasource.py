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
from pathlib import Path

import tableauserverclient as TSC

from _shared import connect_to_server, find_datasource, get_server_env, sanitize_filename


def download(server: TSC.Server, datasource: TSC.DatasourceItem,
             output_dir: Path, include_extract: bool = True) -> str:
    """Download a datasource .tdsx file from Tableau Server.

    Args:
        server: Authenticated TSC.Server instance.
        datasource: The datasource to download.
        output_dir: Directory to save the downloaded file.
        include_extract: If False, downloads metadata only (no .hyper data),
            which is much faster for large extracts. Required to be True
            before repackaging for publish.

    Returns:
        Absolute path to the downloaded .tdsx file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize the datasource name for safe filesystem usage
    safe_name = sanitize_filename(datasource.name)
    filepath = output_dir / safe_name
    downloaded = server.datasources.download(
        datasource.id, filepath=str(filepath), include_extract=include_extract
    )
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
    parser.add_argument("--no-extract", action="store_true",
                        help="Skip the .hyper extract data (metadata only, "
                             "much faster). Not usable for republishing.")
    args = parser.parse_args()

    server_url, token_name, token_secret, site_name, api_version = get_server_env()

    # Connect inside try block so sign_out is always called on success
    server = None
    try:
        server = connect_to_server(
            server_url, token_name, token_secret, site_name, api_version
        )
        ds = find_datasource(server, args.datasource_name, args.project_name)
        tdsx_path = download(server, ds, Path(args.output_dir),
                             include_extract=not args.no_extract)
        print(tdsx_path)
    finally:
        if server is not None:
            server.auth.sign_out()


if __name__ == "__main__":
    main()

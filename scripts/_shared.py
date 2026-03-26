"""Shared utilities for tdsx-describe-fields scripts.

Contains common functions and constants used across multiple scripts
to avoid code duplication.
"""

import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional

# -- Tableau datatype → role/type mapping --
ROLE_TYPE_MAP: dict[str, tuple[str, str]] = {
    "string": ("dimension", "nominal"),
    "integer": ("measure", "quantitative"),
    "real": ("measure", "quantitative"),
    "date": ("dimension", "ordinal"),
    "datetime": ("dimension", "ordinal"),
    "boolean": ("dimension", "nominal"),
}


def find_tds(extract_dir: Path) -> Path:
    """Locate the single .tds file inside an extracted .tdsx directory.

    Args:
        extract_dir: Directory containing extracted .tdsx contents.

    Returns:
        Path to the .tds file.

    Raises:
        FileNotFoundError: If no .tds file is found.
        RuntimeError: If multiple .tds files are found.
    """
    tds_files = list(extract_dir.glob("*.tds"))
    if len(tds_files) == 0:
        raise FileNotFoundError(f"No .tds file found in {extract_dir}")
    if len(tds_files) > 1:
        raise RuntimeError(f"Multiple .tds files found: {tds_files}")
    return tds_files[0]


def safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract all members of a zip file with ZipSlip protection.

    Validates that no archive member extracts outside the destination
    directory (e.g., via '../' traversal or absolute paths).

    Args:
        zf: An opened ZipFile object.
        dest: Target extraction directory.

    Raises:
        ValueError: If a member path would escape the destination directory.
    """
    dest = dest.resolve()
    for member in zf.namelist():
        # Reject absolute paths and parent traversal
        member_path = (dest / member).resolve()
        if not str(member_path).startswith(str(dest)):
            raise ValueError(
                f"Unsafe archive member detected: '{member}' "
                f"would extract outside {dest}"
            )
    zf.extractall(dest)


def get_env(name: str, default: Optional[str] = None,
            required: bool = True) -> str:
    """Read an environment variable with optional default and required check.

    Args:
        name: Environment variable name.
        default: Fallback value if not set.
        required: If True, exit with error when variable is missing.

    Returns:
        The environment variable value.
    """
    value = os.environ.get(name, default)
    if required and not value:
        print(f"Error: Environment variable {name} is not set.", file=sys.stderr)
        sys.exit(1)
    return value or ""


def sanitize_filename(name: str) -> str:
    """Sanitize a string for safe use as a filename on all platforms.

    Replaces any character that is not alphanumeric, dash, underscore,
    dot, or space with an underscore. Then collapses consecutive
    underscores.

    Args:
        name: Raw filename string (e.g., datasource name from server).

    Returns:
        A filesystem-safe filename string.
    """
    # Replace unsafe characters with underscore
    safe = re.sub(r'[^\w\-. ]', '_', name)
    # Collapse consecutive underscores
    safe = re.sub(r'_+', '_', safe)
    return safe.strip('_')


def connect_to_server(server_url: str, token_name: str, token_secret: str,
                      site_name: str, api_version: str):
    """Connect to Tableau Server using Personal Access Token auth.

    Args:
        server_url: Tableau Server URL.
        token_name: Personal Access Token name.
        token_secret: Personal Access Token secret.
        site_name: Tableau site name (empty string for default site).
        api_version: REST API version string.

    Returns:
        An authenticated TSC.Server instance.
    """
    # Import here so scripts that don't use server features
    # don't require tableauserverclient to be installed.
    import tableauserverclient as TSC

    auth = TSC.PersonalAccessTokenAuth(token_name, token_secret, site_name)
    server = TSC.Server(server_url, use_server_version=False)
    server.version = api_version
    server.add_http_options({"verify": False})
    server.auth.sign_in(auth)
    return server


def get_server_env() -> tuple[str, str, str, str, str]:
    """Read all Tableau Server environment variables.

    Returns:
        Tuple of (server_url, token_name, token_secret, site_name, api_version).
    """
    server_url = get_env("TABLEAU_SERVER_URL")
    token_name = get_env("TABLEAU_TOKEN_NAME")
    token_secret = get_env("TABLEAU_TOKEN_SECRET")
    site_name = get_env("TABLEAU_SITE_NAME", default="", required=False)
    api_version = get_env("TABLEAU_API_VERSION", default="3.7", required=False)
    return server_url, token_name, token_secret, site_name, api_version

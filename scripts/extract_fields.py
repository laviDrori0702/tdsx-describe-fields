"""Extract field names and metadata from a Tableau .tdsx file.

Usage: python extract_fields.py <path_to_tdsx>

Outputs (in current working directory):
  - field_descriptions.json  : {"field_name": "", ...} for user/agent editing
  - field_metadata.json      : [{name, tds_name, caption, datatype, role, type, calculation}, ...]
"""

import json
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from _shared import ROLE_TYPE_MAP, find_tds, safe_extractall


def strip_brackets(tds_name: str) -> str:
    """'[Avg_Price_EUR]' -> 'Avg_Price_EUR'"""
    return tds_name.strip("[]")


def extract_fields(tds_path: Path) -> dict[str, dict]:
    """Extract all field definitions from a .tds XML file.

    Scans three sources of field definitions:
    1. Top-level <column> elements (explicit columns).
    2. <column> elements inside <datasource-dependencies> (federated datasources).
    3. <metadata-record> entries in the connection (implicit columns).

    Parameters and internal Tableau objects are excluded.

    Args:
        tds_path: Path to the .tds XML file.

    Returns:
        Dict keyed by TDS name (e.g., '[FieldName]') with field metadata dicts.
    """
    tree = ET.parse(tds_path)
    root = tree.getroot()

    # -- 1. Explicit top-level columns --
    explicit_columns: dict[str, dict] = {}
    for col in root.findall("column"):
        name_attr = col.get("name", "")
        # Skip internal Tableau objects
        if "__tableau_internal_object_id__" in name_attr:
            continue
        # Skip parameters
        if col.get("param-domain-type"):
            continue

        field_name = strip_brackets(name_attr)
        calc_el = col.find("calculation")
        formula = None
        if calc_el is not None:
            formula = calc_el.get("formula")

        explicit_columns[name_attr] = {
            "name": field_name,
            "tds_name": name_attr,
            "caption": col.get("caption"),
            "datatype": col.get("datatype"),
            "role": col.get("role"),
            "type": col.get("type"),
            "calculation": formula,
        }

    # -- 2. Columns inside <datasource-dependencies> (federated/multi-connection) --
    for dep in root.findall(".//datasource-dependencies"):
        # Skip the Parameters datasource — handled separately below
        if dep.get("datasource") == "Parameters":
            continue
        for col in dep.findall("column"):
            name_attr = col.get("name", "")
            if name_attr in explicit_columns:
                continue
            if "__tableau_internal_object_id__" in name_attr:
                continue
            if col.get("param-domain-type"):
                continue

            field_name = strip_brackets(name_attr)
            calc_el = col.find("calculation")
            formula = None
            if calc_el is not None:
                formula = calc_el.get("formula")

            explicit_columns[name_attr] = {
                "name": field_name,
                "tds_name": name_attr,
                "caption": col.get("caption"),
                "datatype": col.get("datatype"),
                "role": col.get("role"),
                "type": col.get("type"),
                "calculation": formula,
            }

    # -- 3. Metadata-record entries (implicit columns from connection) --
    metadata_fields: dict[str, dict] = {}
    connection = root.find("connection")
    if connection is not None:
        for mr in connection.findall(".//metadata-record"):
            if mr.get("class") != "column":
                continue
            local_name_el = mr.find("local-name")
            if local_name_el is None or local_name_el.text is None:
                continue
            local_name = local_name_el.text
            # Skip if already found as an explicit column
            if local_name in explicit_columns:
                continue

            local_type_el = mr.find("local-type")
            datatype = local_type_el.text if local_type_el is not None else "string"

            field_name = strip_brackets(local_name)
            role, col_type = ROLE_TYPE_MAP.get(datatype, ("dimension", "nominal"))

            metadata_fields[local_name] = {
                "name": field_name,
                "tds_name": local_name,
                "caption": None,
                "datatype": datatype,
                "role": role,
                "type": col_type,
                "calculation": None,
            }

    all_fields = {**explicit_columns, **metadata_fields}

    # -- Remove parameter fields --
    param_deps = root.find("datasource-dependencies[@datasource='Parameters']")
    if param_deps is not None:
        for pcol in param_deps.findall("column"):
            pname = pcol.get("name", "")
            qualified = f"[Parameters].{pname}"
            all_fields.pop(qualified, None)
            all_fields.pop(pname, None)

    return all_fields


def main() -> None:
    """Main entry point for field extraction."""
    if len(sys.argv) < 2:
        print("Usage: python extract_fields.py <path_to_tdsx>")
        sys.exit(1)

    tdsx_path = Path(sys.argv[1]).resolve()
    if not tdsx_path.exists():
        print(f"Error: File not found: {tdsx_path}")
        sys.exit(1)
    if tdsx_path.suffix.lower() != ".tdsx":
        print(f"Error: Expected a .tdsx file, got: {tdsx_path.suffix}")
        sys.exit(1)

    tmp_dir = Path(tempfile.mkdtemp(prefix="tdsx_extract_"))
    try:
        # Open .tdsx directly — no need to rename to .zip
        extract_dir = tmp_dir / "extracted"
        with zipfile.ZipFile(tdsx_path, "r") as zf:
            safe_extractall(zf, extract_dir)

        tds_path = find_tds(extract_dir)
        all_fields = extract_fields(tds_path)

        metadata_list = sorted(all_fields.values(), key=lambda f: f["name"])
        descriptions_dict = {f["name"]: "" for f in metadata_list}

        cwd = Path.cwd()
        desc_path = cwd / "field_descriptions.json"
        meta_path = cwd / "field_metadata.json"

        with open(desc_path, "w", encoding="utf-8") as f:
            json.dump(descriptions_dict, f, indent=2, ensure_ascii=False)

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata_list, f, indent=2, ensure_ascii=False)

        print(f"Extracted {len(metadata_list)} fields from: {tdsx_path.name}")
        print(f"  -> {desc_path}")
        print(f"  -> {meta_path}")
        print()
        print("Fields found:")
        for field in metadata_list:
            calc_note = "  [calculated]" if field["calculation"] else ""
            print(f"  - {field['name']} ({field['datatype']}, {field['role']}){calc_note}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

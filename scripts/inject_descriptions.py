"""Inject field descriptions into a Tableau .tdsx file.

Usage: python inject_descriptions.py <path_to_tdsx> [--descriptions <json_path>]

Reads field_descriptions.json (from CWD or specified path), modifies the .tds XML
to add <desc> elements, and produces:
  - <name>_with_descriptions.tdsx  (repackaged datasource)
  - <name>_with_descriptions.tds   (standalone TDS for local testing)
"""

import json
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from _shared import ROLE_TYPE_MAP, find_tds, safe_extractall

FONT_ATTRS = {
    "fontcolor": "#3c4043",
    "fontname": "Inter",
    "fontsize": "11",
}


def make_desc_element(description_text: str) -> ET.Element:
    """Create a <desc> XML element with formatted text styling.

    Args:
        description_text: The description string to embed.

    Returns:
        An ET.Element representing the <desc> tag.
    """
    desc = ET.Element("desc")
    fmt = ET.SubElement(desc, "formatted-text")
    run = ET.SubElement(fmt, "run", FONT_ATTRS)
    run.text = description_text
    return desc


def build_metadata_lookup(root: ET.Element) -> dict:
    """Build a map of tds_name -> metadata from <metadata-record> entries.

    Args:
        root: The root XML element of the TDS.

    Returns:
        Dict keyed by local-name with datatype/role/type metadata.
    """
    lookup = {}
    connection = root.find("connection")
    if connection is None:
        return lookup
    for mr in connection.findall(".//metadata-record"):
        if mr.get("class") != "column":
            continue
        local_name_el = mr.find("local-name")
        if local_name_el is None or local_name_el.text is None:
            continue
        local_name = local_name_el.text
        local_type_el = mr.find("local-type")
        datatype = local_type_el.text if local_type_el is not None else "string"
        role, col_type = ROLE_TYPE_MAP.get(datatype, ("dimension", "nominal"))
        lookup[local_name] = {
            "datatype": datatype,
            "role": role,
            "type": col_type,
        }
    return lookup


def find_column_insert_index(root: ET.Element) -> int:
    """Find the index where new <column> elements should be inserted.

    New columns go before <extract>, <layout>, <semantic-values>,
    or <object-graph> to respect TDS schema order.

    Args:
        root: The root XML element of the TDS.

    Returns:
        Integer index for insertion.
    """
    markers = ["extract", "layout", "semantic-values", "object-graph"]
    children = list(root)
    for i, child in enumerate(children):
        if child.tag in markers:
            return i
    return len(children)


def detect_xml_encoding(file_path: Path) -> str:
    """Detect the encoding declared in an XML file's declaration.

    Reads the first line of the file in binary mode and parses
    the encoding attribute from the <?xml ...?> declaration.
    Defaults to 'utf-8' if no declaration or encoding is found.

    Args:
        file_path: Path to the XML file.

    Returns:
        Encoding string (e.g., 'utf-8', 'windows-1252').
    """
    with open(file_path, "rb") as f:
        # Read enough bytes for the XML declaration (first 200 bytes)
        header = f.read(200)
    match = re.search(rb'encoding=["\']([^"\']+)["\']', header)
    if match:
        return match.group(1).decode("ascii")
    return "utf-8"


def inject_descriptions(tds_path: Path,
                        descriptions: dict[str, str]) -> tuple[int, int]:
    """Inject description elements into TDS XML columns.

    For each non-empty description:
    - If the column exists: replace or add <desc> element.
    - If the column only exists in metadata: create a new <column> element.
    - If the field is not found anywhere: print a warning and skip.

    Args:
        tds_path: Path to the .tds XML file (modified in-place).
        descriptions: Dict of field_name -> description_text.

    Returns:
        Tuple of (injected_count, created_count).
    """
    # Detect original encoding before parsing
    original_encoding = detect_xml_encoding(tds_path)

    tree = ET.parse(tds_path)
    root = tree.getroot()

    existing_columns: dict[str, ET.Element] = {}
    for col in root.findall("column"):
        name_attr = col.get("name", "")
        existing_columns[name_attr] = col

    metadata_lookup = build_metadata_lookup(root)
    insert_idx = find_column_insert_index(root)

    injected = 0
    created = 0

    for field_name, desc_text in descriptions.items():
        if not desc_text.strip():
            continue

        tds_name = f"[{field_name}]"

        if tds_name in existing_columns:
            col_el = existing_columns[tds_name]
            old_desc = col_el.find("desc")
            if old_desc is not None:
                col_el.remove(old_desc)
            col_el.append(make_desc_element(desc_text))
            injected += 1
        elif tds_name in metadata_lookup:
            meta = metadata_lookup[tds_name]
            col_el = ET.Element("column")
            col_el.set("datatype", meta["datatype"])
            col_el.set("name", tds_name)
            col_el.set("role", meta["role"])
            col_el.set("type", meta["type"])
            col_el.append(make_desc_element(desc_text))
            root.insert(insert_idx, col_el)
            insert_idx += 1
            created += 1
        else:
            print(f"  Warning: field '{field_name}' not found in TDS, skipping")

    ET.indent(tree, space="  ")
    # Preserve the original encoding when rewriting
    tree.write(tds_path, encoding=original_encoding, xml_declaration=True)

    return injected, created


def create_tdsx(original_tdsx: Path, extract_dir: Path,
                output_path: Path, tds_filename: str) -> None:
    """Repackage a .tdsx, replacing only the .tds with the modified version.

    Iterates all entries from the original archive and copies them as-is,
    except for the .tds file which is replaced with the modified version
    from extract_dir. This preserves Extras/, custom images, .hyper files
    outside Data/, and any other non-standard archive entries.

    Args:
        original_tdsx: Path to the original .tdsx file (for reading entries).
        extract_dir: Directory containing the modified .tds and extracted files.
        output_path: Path for the output .tdsx file.
        tds_filename: Name of the .tds file inside the archive.
    """
    with zipfile.ZipFile(original_tdsx, "r") as original_zf:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as out_zf:
            for entry in original_zf.namelist():
                if entry == tds_filename:
                    # Replace the .tds with the modified version
                    out_zf.write(extract_dir / tds_filename, tds_filename)
                else:
                    # Copy all other entries as-is from the original
                    out_zf.writestr(entry, original_zf.read(entry))


def main() -> None:
    """Main entry point for description injection."""
    if len(sys.argv) < 2:
        print("Usage: python inject_descriptions.py <path_to_tdsx> "
              "[--descriptions <json_path>]")
        sys.exit(1)

    tdsx_path = Path(sys.argv[1]).resolve()
    if not tdsx_path.exists():
        print(f"Error: File not found: {tdsx_path}")
        sys.exit(1)

    desc_path = Path.cwd() / "field_descriptions.json"
    if "--descriptions" in sys.argv:
        idx = sys.argv.index("--descriptions")
        if idx + 1 < len(sys.argv):
            desc_path = Path(sys.argv[idx + 1]).resolve()

    if not desc_path.exists():
        print(f"Error: Descriptions file not found: {desc_path}")
        sys.exit(1)

    with open(desc_path, "r", encoding="utf-8") as f:
        descriptions = json.load(f)

    non_empty = sum(1 for v in descriptions.values() if v.strip())
    if non_empty == 0:
        print("Error: All descriptions are empty. Fill in at least one description.")
        sys.exit(1)

    tmp_dir = Path(tempfile.mkdtemp(prefix="tdsx_inject_"))
    try:
        # Open .tdsx directly — no need to rename to .zip
        extract_dir = tmp_dir / "extracted"
        with zipfile.ZipFile(tdsx_path, "r") as zf:
            safe_extractall(zf, extract_dir)

        tds_path = find_tds(extract_dir)

        print(f"Injecting descriptions into: {tdsx_path.name}")
        injected, created = inject_descriptions(tds_path, descriptions)
        print(f"  Updated {injected} existing columns, created {created} new column tags")

        output_dir = tdsx_path.parent
        stem = tdsx_path.stem
        if stem.endswith("_with_descriptions"):
            out_stem = stem
        else:
            out_stem = stem + "_with_descriptions"

        # Standalone .tds for local testing
        out_tds = output_dir / (out_stem + ".tds")
        shutil.copy2(tds_path, out_tds)
        print(f"  -> {out_tds}")

        # Repackaged .tdsx preserving all original archive entries
        out_tdsx = output_dir / (out_stem + ".tdsx")
        create_tdsx(tdsx_path, extract_dir, out_tdsx, tds_path.name)
        print(f"  -> {out_tdsx}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

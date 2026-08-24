"""Extract the source query (custom SQL, or table/join structure) from a .tdsx.

Usage: python extract_sql.py <path_to_tdsx> [--out custom_sql.sql]

Writes the datasource's underlying query to a .sql file so it can be read when
drafting a datasource-level description. Two cases:

  1. Custom SQL  -- every <relation type='text'> body, deduplicated. Tableau
     stores the same query once per connection (live + extract), so identical
     bodies collapse to a single block.
  2. No custom SQL -- falls back to the physical table/join structure, so a
     table-based datasource still yields something describable.
"""

import argparse
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from _shared import find_tds, safe_extractall

# Relation types that carry a raw query body rather than a table reference.
TEXT_RELATION_TYPES = frozenset({"text"})


def collect_sql_relations(root: ET.Element) -> list[tuple[str, str]]:
    """Collect deduplicated custom SQL bodies from <relation type='text'> nodes.

    Args:
        root: Root element of the .tds XML.

    Returns:
        List of (relation_name, sql_text) pairs, one per unique SQL body,
        in document order. Duplicate bodies (live + extract connection) are
        dropped, keeping the first relation name that carried them.
    """
    seen_bodies: set[str] = set()
    relations: list[tuple[str, str]] = []

    for relation in root.iter("relation"):
        if relation.get("type") not in TEXT_RELATION_TYPES:
            continue
        # ElementTree folds CDATA into .text, so the SQL arrives as plain text.
        body = (relation.text or "").strip()
        if not body or body in seen_bodies:
            continue
        seen_bodies.add(body)
        relations.append((relation.get("name") or "unnamed", body))

    return relations


def collect_table_structure(root: ET.Element) -> list[str]:
    """Describe the physical table/join structure of a non-custom-SQL datasource.

    Args:
        root: Root element of the .tds XML.

    Returns:
        List of human-readable lines describing tables and join clauses.
        Empty if the datasource has no table relations either.
    """
    lines: list[str] = []

    tables = []
    for relation in root.iter("relation"):
        if relation.get("type") != "table":
            continue
        table_ref = relation.get("table") or relation.get("name") or "?"
        if table_ref not in tables:
            tables.append(table_ref)
    if tables:
        lines.append("Tables:")
        lines.extend(f"  {table}" for table in tables)

    joins = []
    for relation in root.iter("relation"):
        if relation.get("type") != "join":
            continue
        clause = relation.find("clause")
        # The join predicate lives in nested <expression> nodes; flatten the
        # op attributes into a readable infix string.
        predicate = flatten_expression(clause.find("expression")) if clause is not None else "?"
        joins.append(f"  {relation.get('join', 'join')}: {predicate}")
    if joins:
        lines.append("Joins:")
        lines.extend(joins)

    return lines


def flatten_expression(expression: ET.Element | None) -> str:
    """Flatten a nested Tableau <expression> tree into an infix string.

    Args:
        expression: An <expression> element, or None.

    Returns:
        A readable string such as "[a].[id] = [b].[id]", or '?' if absent.
    """
    if expression is None:
        return "?"
    op = expression.get("op", "")
    children = list(expression)
    if not children:
        return op
    if len(children) == 1:
        return f"{op}({flatten_expression(children[0])})"
    return f" {op} ".join(flatten_expression(child) for child in children)


def render(sql_relations: list[tuple[str, str]], table_lines: list[str]) -> str:
    """Render the extracted query information into the output file body.

    Args:
        sql_relations: Deduplicated (name, sql) pairs from custom SQL relations.
        table_lines: Fallback table/join description lines.

    Returns:
        The full text to write to the .sql file.
    """
    if sql_relations:
        blocks = [f"-- relation: {name}\n{sql}" for name, sql in sql_relations]
        return "\n\n".join(blocks) + "\n"

    if table_lines:
        commented = "\n".join(f"-- {line}" for line in table_lines)
        return f"-- No custom SQL. Physical table structure:\n{commented}\n"

    return "-- No custom SQL and no table relations found in this datasource.\n"


def read_tds_root(tdsx_path: Path) -> ET.Element:
    """Parse the .tds XML out of a .tdsx archive (or a bare .tds file).

    Args:
        tdsx_path: Path to a .tdsx or .tds file.

    Returns:
        The root element of the .tds XML.
    """
    if tdsx_path.suffix.lower() == ".tds":
        return ET.parse(tdsx_path).getroot()

    tmp_dir = Path(tempfile.mkdtemp(prefix="tdsx_sql_"))
    try:
        extract_dir = tmp_dir / "extracted"
        with zipfile.ZipFile(tdsx_path, "r") as zf:
            safe_extractall(zf, extract_dir)
        return ET.parse(find_tds(extract_dir)).getroot()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    """Main entry point for source-query extraction."""
    parser = argparse.ArgumentParser(
        description="Extract custom SQL (or table structure) from a .tdsx."
    )
    parser.add_argument("tdsx_path", help="Path to the .tdsx (or .tds) file")
    parser.add_argument("--out", default="custom_sql.sql",
                        help="Output path (default: custom_sql.sql in CWD)")
    args = parser.parse_args()

    tdsx_path = Path(args.tdsx_path).resolve()
    if not tdsx_path.exists():
        print(f"Error: File not found: {tdsx_path}", file=sys.stderr)
        sys.exit(1)

    root = read_tds_root(tdsx_path)
    sql_relations = collect_sql_relations(root)
    table_lines = [] if sql_relations else collect_table_structure(root)

    out_path = Path(args.out).resolve()
    out_path.write_text(render(sql_relations, table_lines), encoding="utf-8")

    if sql_relations:
        print(f"Extracted {len(sql_relations)} unique custom SQL "
              f"relation(s) -> {out_path}")
        for name, sql in sql_relations:
            print(f"  - {name}: {len(sql.splitlines())} lines")
    elif table_lines:
        print(f"No custom SQL; wrote table/join structure -> {out_path}")
    else:
        print(f"No custom SQL and no table relations found -> {out_path}")


if __name__ == "__main__":
    main()

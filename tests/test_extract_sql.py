"""Tests for extract_sql.py relation parsing.

Covers the three shapes a .tds can take:
  1. Custom SQL duplicated across the live and extract connections (the real
     case observed in subscriptionsLifecycle.tdsx) -- must collapse to one block.
  2. Two genuinely different custom SQL relations -- must keep both.
  3. A table-only datasource with a join -- must fall back to table structure.

Run: python -m pytest tests/test_extract_sql.py
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from extract_sql import (  # noqa: E402
    collect_sql_relations,
    collect_table_structure,
    render,
)

# Same SQL under two connections, exactly as Tableau writes it for an extract.
DUPLICATE_SQL_TDS = """<datasource>
  <connection class='federated'>
    <relation connection='postgres.aaa' name='Custom SQL Query' type='text'>
      <![CDATA[SELECT 1 AS a]]>
    </relation>
    <relation connection='extract.bbb' name='Custom SQL Query' type='text'>
      <![CDATA[SELECT 1 AS a]]>
    </relation>
  </connection>
</datasource>"""

DISTINCT_SQL_TDS = """<datasource>
  <connection class='federated'>
    <relation name='Query A' type='text'><![CDATA[SELECT 1 AS a]]></relation>
    <relation name='Query B' type='text'><![CDATA[SELECT 2 AS b]]></relation>
  </connection>
</datasource>"""

TABLE_ONLY_TDS = """<datasource>
  <connection class='federated'>
    <relation join='inner' type='join'>
      <clause type='join'>
        <expression op='='>
          <expression op='[orders].[id]' />
          <expression op='[lines].[order_id]' />
        </expression>
      </clause>
      <relation name='orders' table='[public].[orders]' type='table' />
      <relation name='lines' table='[public].[lines]' type='table' />
    </relation>
  </connection>
</datasource>"""


def test_duplicate_sql_is_deduplicated():
    """The same query under two connections yields one block, not two."""
    relations = collect_sql_relations(ET.fromstring(DUPLICATE_SQL_TDS))
    assert len(relations) == 1
    assert relations[0] == ("Custom SQL Query", "SELECT 1 AS a")


def test_distinct_sql_relations_are_both_kept():
    """Two different queries are not collapsed by the dedupe."""
    relations = collect_sql_relations(ET.fromstring(DISTINCT_SQL_TDS))
    assert [name for name, _ in relations] == ["Query A", "Query B"]


def test_table_only_falls_back_to_structure():
    """A datasource with no custom SQL reports its tables and join predicate."""
    root = ET.fromstring(TABLE_ONLY_TDS)
    assert collect_sql_relations(root) == []

    lines = collect_table_structure(root)
    text = "\n".join(lines)
    assert "[public].[orders]" in text
    assert "[public].[lines]" in text
    assert "inner" in text
    assert "[orders].[id] = [lines].[order_id]" in text


def test_render_comments_out_the_fallback():
    """Fallback output is fully commented so the file stays valid SQL."""
    root = ET.fromstring(TABLE_ONLY_TDS)
    body = render([], collect_table_structure(root))
    assert all(line.startswith("--") for line in body.strip().splitlines())


def test_render_labels_each_sql_block():
    """Each SQL block carries a -- relation: header naming its source."""
    relations = collect_sql_relations(ET.fromstring(DISTINCT_SQL_TDS))
    body = render(relations, [])
    assert "-- relation: Query A" in body
    assert "-- relation: Query B" in body


def test_empty_datasource_is_not_an_error():
    """A datasource with no relations at all renders a note, not a crash."""
    root = ET.fromstring("<datasource><connection /></datasource>")
    assert "No custom SQL and no table relations" in render([], collect_table_structure(root))


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-v"]))

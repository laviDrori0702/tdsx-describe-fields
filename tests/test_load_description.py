"""Tests for the description-file guard in publish_datasource.py.

The guard is the only thing standing between an unreviewed inferred line and a
description the in-dashboard AI agent will treat as ground truth, so each exit
path gets a check:
  - clean text passes through
  - a '??' marked line aborts with exit 3
  - missing / empty files abort with exit 1

Run: python -m pytest tests/test_load_description.py

tableauserverclient is imported at publish_datasource module scope; the test is
skipped rather than failed when it isn't installed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

publish_datasource = pytest.importorskip(
    "publish_datasource", reason="requires tableauserverclient"
)
load_description = publish_datasource.load_description

CLEAN_DESCRIPTION = """Purpose: Daily snapshots of B2B subscription contracts.
Grain: One row per contract per norm_date.
Coverage: 2025-01-01 to current date; usable max date is MAX(norm_date) - 2.
Aggregation: num_contracts is a point-in-time stock -- do not sum across dates.
"""

MARKED_DESCRIPTION = """Purpose: Daily snapshots of B2B subscription contracts.
?? Grain: One row per contract per norm_date.
Coverage: 2025-01-01 to current date.
  ?? Scope: Excludes cancelled subscriptions.
"""


def test_clean_description_is_returned_stripped(tmp_path):
    """A description with no markers passes through, whitespace trimmed."""
    path = tmp_path / "datasource_description.txt"
    path.write_text(CLEAN_DESCRIPTION, encoding="utf-8")

    result = load_description(path)

    assert result.startswith("Purpose:")
    assert result.endswith("across dates.")


def test_unverified_marker_exits_3(tmp_path, capsys):
    """Any '??' line blocks the publish with exit code 3, listing the lines."""
    path = tmp_path / "datasource_description.txt"
    path.write_text(MARKED_DESCRIPTION, encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        load_description(path)

    assert excinfo.value.code == 3
    stderr = capsys.readouterr().err
    # Both the leading and the indented marker are caught.
    assert "2 line(s)" in stderr
    assert "Grain" in stderr
    assert "Scope" in stderr


def test_missing_file_exits_1(tmp_path):
    """A nonexistent description file is a plain error, not a marker error."""
    with pytest.raises(SystemExit) as excinfo:
        load_description(tmp_path / "nope.txt")
    assert excinfo.value.code == 1


def test_empty_file_exits_1(tmp_path):
    """A whitespace-only file would publish a blank description, so it aborts."""
    path = tmp_path / "datasource_description.txt"
    path.write_text("   \n\n  ", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        load_description(path)
    assert excinfo.value.code == 1


def test_over_soft_limit_warns_but_passes(tmp_path, capsys):
    """The length budget is advisory: it warns, it does not block."""
    path = tmp_path / "datasource_description.txt"
    path.write_text("Purpose: " + "x" * 2000, encoding="utf-8")

    result = load_description(path)

    assert len(result) > publish_datasource.DESCRIPTION_SOFT_LIMIT
    assert "soft target" in capsys.readouterr().err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

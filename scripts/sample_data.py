"""Extract .hyper data from a .tdsx and sample rows for field understanding.

Usage: python sample_data.py <path_to_tdsx> [--rows 500]

Outputs (in current working directory):
  - data_sample.csv  : random sample of rows from the hyper extract

Also prints column-level summary statistics to stdout.
"""

import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import pantab as pt

from _shared import safe_extractall


def extract_hyper(tdsx_path: Path, tmp_dir: Path) -> Path:
    """Unzip the .tdsx and locate the .hyper file inside.

    Args:
        tdsx_path: Path to the .tdsx file.
        tmp_dir: Temporary directory for extraction.

    Returns:
        Path to the extracted .hyper file.
    """
    extract_dir = tmp_dir / "extracted"
    with zipfile.ZipFile(tdsx_path, "r") as zf:
        safe_extractall(zf, extract_dir)

    hyper_files = list(extract_dir.rglob("*.hyper"))
    if not hyper_files:
        print(f"Error: No .hyper file found inside {tdsx_path.name}", file=sys.stderr)
        sys.exit(1)

    return hyper_files[0]


def read_hyper(hyper_path: Path) -> pd.DataFrame:
    """Read the first table from a .hyper file into a DataFrame.

    If multiple tables exist, all table names are logged to stderr
    with a warning indicating which one was selected.

    Args:
        hyper_path: Path to the .hyper file.

    Returns:
        DataFrame containing the table data.
    """
    frames = pt.frames_from_hyper(str(hyper_path))
    tables = list(frames.keys())

    if not tables:
        print("Error: No tables found in .hyper file", file=sys.stderr)
        sys.exit(1)

    if len(tables) > 1:
        print(
            f"Warning: {len(tables)} tables found in .hyper file. "
            f"Sampling only the first table.",
            file=sys.stderr,
        )
        for i, table_name in enumerate(tables):
            marker = " <-- sampled" if i == 0 else ""
            print(f"  [{i}] {table_name}{marker}", file=sys.stderr)

    selected = tables[0]
    df = frames[selected]
    print(
        f"Table: {selected}  |  {len(df)} rows x {len(df.columns)} columns",
        file=sys.stderr,
    )
    return df


def print_summary(df: pd.DataFrame) -> None:
    """Print per-column summary stats to stdout for the agent to read.

    Args:
        df: The full DataFrame (not the sample) for accurate statistics.
    """
    print("\n=== Column Summary ===\n")
    for col in df.columns:
        series = df[col]
        non_null = series.notna().sum()
        unique = series.nunique()
        dtype = series.dtype

        sample_vals = series.dropna().unique()[:5]
        sample_str = ", ".join(str(v) for v in sample_vals)

        print(f"  {col}")
        print(f"    dtype: {dtype}  |  non-null: {non_null}/{len(df)}  |  unique: {unique}")
        print(f"    sample values: {sample_str}")

        if pd.api.types.is_numeric_dtype(series):
            print(f"    min: {series.min()}  |  max: {series.max()}  |  mean: {series.mean():.4f}")

        print()


def main() -> None:
    """Main entry point for data sampling."""
    parser = argparse.ArgumentParser(
        description="Sample data from a .tdsx hyper extract."
    )
    parser.add_argument("tdsx_path", help="Path to the .tdsx file")
    parser.add_argument("--rows", type=int, default=500,
                        help="Number of rows to sample (default: 500)")
    args = parser.parse_args()

    tdsx_path = Path(args.tdsx_path).resolve()
    if not tdsx_path.exists():
        print(f"Error: File not found: {tdsx_path}", file=sys.stderr)
        sys.exit(1)
    if tdsx_path.suffix.lower() != ".tdsx":
        print(f"Error: Expected a .tdsx file, got: {tdsx_path.suffix}", file=sys.stderr)
        sys.exit(1)

    tmp_dir = Path(tempfile.mkdtemp(prefix="tdsx_sample_"))
    try:
        hyper_path = extract_hyper(tdsx_path, tmp_dir)
        df = read_hyper(hyper_path)

        n_sample = min(args.rows, len(df))
        sample_df = df.sample(n=n_sample, random_state=42)

        csv_path = Path.cwd() / "data_sample.csv"
        sample_df.to_csv(csv_path, index=False)

        print(f"Sampled {n_sample} rows -> {csv_path}", file=sys.stderr)
        # Run summary on the full dataset for accurate stats
        print_summary(df)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

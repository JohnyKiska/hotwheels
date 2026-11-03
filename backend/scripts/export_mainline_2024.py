#!/usr/bin/env python3
"""
Read-only export of the Mainline 2024 catalog from TEST_V2.

Expected location:
    backend/scripts/export_mainline_2024.py

Database:
    backend/hotwheels_import_test_v2.db

Output:
    backend/exports/mainline_2024_export.json

The database is opened read-only. This script never runs an importer,
never changes the schema, and never updates database records.
An existing output file is never overwritten.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DB_PATH = BACKEND_DIR / "hotwheels_import_test_v2.db"
OUTPUT_PATH = BACKEND_DIR / "exports" / "mainline_2024_export.json"

PRODUCT_LINE_NAME = "Mainline"
PRODUCT_LINE_TYPE = "mainline"
TARGET_YEAR = 2024

EXPECTED_COUNTS = {
    "releases": 441,
    "castings": 249,
    "series": 36,
    "source_records": 441,
    "evidence": 2646,
    "release_series": 441,
    "release_identifiers": 882,
    "evidence_releases": 2646,
    "evidence_castings": 441,
    "evidence_series": 882,
}

# These tables were inspected in TEST_V2 and currently contain zero rows.
# If any of them gains data before export, this script stops rather than
# silently omitting newly introduced relationships.
EXPECTED_EMPTY_TABLES = (
    "brands",
    "manufacturers",
    "casting_brands",
    "casting_identifiers",
    "casting_origins",
    "casting_variant_identifiers",
    "release_brands",
    "product_line_brands",
    "manufacturer_brands",
    "package_identifiers",
    "package_releases",
    "media_assets",
    "change_log",
    "conflicts",
    "change_log_evidence",
    "conflict_evidence",
    "evidence_brands",
    "evidence_casting_origins",
    "evidence_casting_variants",
    "evidence_manufacturers",
    "evidence_origin_objects",
    "evidence_origin_specifications",
    "evidence_origin_variants",
    "evidence_packages",
    "casting_variants",
    "origin_objects",
    "origin_specifications",
    "origin_variants",
    "packages",
)

EVIDENCE_LINK_TABLES = (
    "evidence_releases",
    "evidence_castings",
    "evidence_series",
    "evidence_brands",
    "evidence_casting_origins",
    "evidence_casting_variants",
    "evidence_manufacturers",
    "evidence_origin_objects",
    "evidence_origin_specifications",
    "evidence_origin_variants",
    "evidence_packages",
    "change_log_evidence",
    "conflict_evidence",
)

RELATED_TABLES = EXPECTED_EMPTY_TABLES


def fail(message: str) -> None:
    raise RuntimeError(message)


def qident(identifier: str) -> str:
    """Safely quote a SQLite identifier obtained from schema introspection."""
    return '"' + identifier.replace('"', '""') + '"'


def table_names(con: sqlite3.Connection) -> set[str]:
    rows = con.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {row["name"] for row in rows}


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [
        row["name"]
        for row in con.execute(f"PRAGMA table_info({qident(table)})")
    ]


def table_schema(con: sqlite3.Connection, table: str) -> dict[str, Any]:
    info = list(con.execute(f"PRAGMA table_info({qident(table)})"))
    foreign_keys = list(
        con.execute(f"PRAGMA foreign_key_list({qident(table)})")
    )
    return {
        "columns": [
            {
                "name": row["name"],
                "type": row["type"],
                "notnull": bool(row["notnull"]),
                "primary_key_position": row["pk"],
            }
            for row in info
        ],
        "foreign_keys": [
            {
                "column": row["from"],
                "referenced_table": row["table"],
                "referenced_column": row["to"],
                "constraint_id": row["id"],
                "sequence": row["seq"],
            }
            for row in foreign_keys
        ],
    }


def fetch_all(
    con: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    return [dict(row) for row in con.execute(sql, params).fetchall()]


def fetch_by_ids(
    con: sqlite3.Connection,
    table: str,
    ids: set[str],
    id_column: str = "id",
) -> list[dict[str, Any]]:
    if not ids:
        return []

    columns = table_columns(con, table)
    if id_column not in columns:
        fail(f"{table} has no expected ID column {id_column!r}")

    values = sorted(ids)
    result: list[dict[str, Any]] = []

    # Stay comfortably below SQLite's common bound-variable limits.
    for offset in range(0, len(values), 500):
        batch = values[offset:offset + 500]
        placeholders = ",".join("?" for _ in batch)
        result.extend(
            fetch_all(
                con,
                f"SELECT * FROM {qident(table)} "
                f"WHERE {qident(id_column)} IN ({placeholders})",
                tuple(batch),
            )
        )
    return result


def fetch_link_rows(
    con: sqlite3.Connection,
    table: str,
    filter_column: str,
    ids: set[str],
) -> list[dict[str, Any]]:
    if not ids:
        return []

    if filter_column not in table_columns(con, table):
        fail(f"{table} has no filter column {filter_column!r}")

    values = sorted(ids)
    result: list[dict[str, Any]] = []

    for offset in range(0, len(values), 500):
        batch = values[offset:offset + 500]
        placeholders = ",".join("?" for _ in batch)
        result.extend(
            fetch_all(
                con,
                f"SELECT * FROM {qident(table)} "
                f"WHERE {qident(filter_column)} IN ({placeholders})",
                tuple(batch),
            )
        )
    return result


def ids_from(rows: list[dict[str, Any]], column: str = "id") -> set[str]:
    return {
        row[column]
        for row in rows
        if row.get(column) is not None
    }


def assert_refs(
    label: str,
    referenced: set[str],
    available: set[str],
) -> None:
    missing = referenced - available
    if missing:
        fail(
            f"{label}: {len(missing)} unresolved references; "
            f"examples: {sorted(missing)[:10]}"
        )


def assert_count(name: str, actual: int) -> None:
    expected = EXPECTED_COUNTS[name]
    if actual != expected:
        fail(f"{name}: expected {expected}, found {actual}")
    print(f"  {name}: {actual} OK")


def assert_empty_tables(
    con: sqlite3.Connection,
    existing_tables: set[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for table in EXPECTED_EMPTY_TABLES:
        if table not in existing_tables:
            fail(f"Previously inspected table is now missing: {table}")

        count = con.execute(
            f"SELECT COUNT(*) FROM {qident(table)}"
        ).fetchone()[0]
        counts[table] = count

        if count != 0:
            fail(
                f"{table} was expected to be empty but contains "
                f"{count} rows. Export has stopped to avoid omission."
            )

    return counts


def get_ancestor_chain(
    con: sqlite3.Connection,
    node_id: str,
) -> list[dict[str, Any]]:
    """Return year node and ancestors, stopping at the actual root."""
    chain: list[dict[str, Any]] = []
    visited: set[str] = set()
    current_id: str | None = node_id

    while current_id is not None:
        if current_id in visited:
            fail("Cycle detected in catalog_nodes.parent_id hierarchy.")
        visited.add(current_id)

        rows = fetch_all(
            con,
            "SELECT * FROM catalog_nodes WHERE id = ?",
            (current_id,),
        )
        if len(rows) != 1:
            fail(f"Missing or duplicate catalog node: {current_id}")

        node = rows[0]
        chain.append(node)
        current_id = node.get("parent_id")

    chain.reverse()
    return chain


def get_descendants(
    con: sqlite3.Connection,
    node_id: str,
) -> list[dict[str, Any]]:
    return fetch_all(
        con,
        """
        WITH RECURSIVE descendants AS (
            SELECT *
            FROM catalog_nodes
            WHERE id = ?

            UNION ALL

            SELECT child.*
            FROM catalog_nodes AS child
            JOIN descendants AS parent
              ON child.parent_id = parent.id
        )
        SELECT *
        FROM descendants
        ORDER BY node_type, sort_order, id
        """,
        (node_id,),
    )


def main() -> None:
    print("=" * 68)
    print("MAINLINE 2024 READ-ONLY EXPORT")
    print("=" * 68)

    if not DB_PATH.is_file():
        fail(f"Database not found: {DB_PATH}")

    if OUTPUT_PATH.exists():
        fail(
            f"Output already exists: {OUTPUT_PATH}\n"
            "The script will not overwrite it. Inspect or move it manually."
        )

    uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row

    try:
        con.execute("PRAGMA query_only = ON")
        if con.execute("PRAGMA query_only").fetchone()[0] != 1:
            fail("Could not enable SQLite query_only mode.")

        tables = table_names(con)

        required_tables = {
            "product_lines", "catalog_nodes", "releases", "castings",
            "series", "release_series", "catalog_identifiers",
            "identifier_types", "release_identifiers", "evidence",
            "evidence_releases", "evidence_castings", "evidence_series",
            "source_records", "sources",
        }
        missing_tables = required_tables - tables
        if missing_tables:
            fail(f"Required tables missing: {sorted(missing_tables)}")

        print("\n[1/8] Checking inspected empty tables")
        empty_table_counts = assert_empty_tables(con, tables)
        print(f"  {len(empty_table_counts)} tables checked and empty")

        print("\n[2/8] Locating Mainline 2024")
        product_lines = fetch_all(
            con,
            """
            SELECT *
            FROM product_lines
            WHERE name = ? AND line_type = ?
            """,
            (PRODUCT_LINE_NAME, PRODUCT_LINE_TYPE),
        )
        if len(product_lines) != 1:
            fail(
                "Expected exactly one Mainline product line; "
                f"found {len(product_lines)}"
            )
        product_line = product_lines[0]
        product_line_id = product_line["id"]

        year_nodes = fetch_all(
            con,
            """
            SELECT year_node.*
            FROM catalog_nodes AS year_node
            JOIN catalog_nodes AS line_node
              ON year_node.parent_id = line_node.id
            WHERE year_node.node_type = 'year'
              AND year_node.catalog_year = ?
              AND line_node.node_type = 'product_line'
              AND line_node.product_line_id = ?
            """,
            (TARGET_YEAR, product_line_id),
        )
        if len(year_nodes) != 1:
            fail(
                "Expected exactly one Mainline 2024 year node; "
                f"found {len(year_nodes)}"
            )

        year_node = year_nodes[0]
        ancestors = get_ancestor_chain(con, year_node["id"])
        descendants = get_descendants(con, year_node["id"])

        # The top ancestor is included without assuming a particular
        # node_type label for the root.
        tree_by_id = {row["id"]: row for row in ancestors + descendants}
        catalog_tree = list(tree_by_id.values())

        if not ancestors or ancestors[-1]["id"] != year_node["id"]:
            fail("Ancestor chain does not terminate at the selected year node.")

        ancestor_line_ids = {
            row.get("product_line_id")
            for row in ancestors
            if row.get("product_line_id") is not None
        }
        if product_line_id not in ancestor_line_ids:
            fail("Mainline product line is not in the year node's ancestor chain.")

        release_ids = {
            row["release_id"]
            for row in descendants
            if row.get("release_id") is not None
        }
        tree_series_ids = {
            row["series_id"]
            for row in descendants
            if row.get("series_id") is not None
        }

        print(f"  Catalog tree nodes: {len(catalog_tree)}")
        print(f"  Release IDs in tree: {len(release_ids)}")
        print(f"  Series IDs in tree: {len(tree_series_ids)}")

        print("\n[3/8] Exporting Releases, Castings and Series")
        releases = fetch_by_ids(con, "releases", release_ids)
        assert_refs("Catalog tree → Releases", release_ids, ids_from(releases))

        if any(row.get("catalog_year") != TARGET_YEAR for row in releases):
            fail("A selected Release has catalog_year other than 2024.")

        casting_ids = {
            row["casting_id"]
            for row in releases
            if row.get("casting_id") is not None
        }
        castings = fetch_by_ids(con, "castings", casting_ids)
        assert_refs("Releases → Castings", casting_ids, ids_from(castings))

        release_series = fetch_link_rows(
            con, "release_series", "release_id", release_ids
        )
        linked_series_ids = {
            row["series_id"]
            for row in release_series
            if row.get("series_id") is not None
        }
        series_ids = tree_series_ids | linked_series_ids
        series = fetch_by_ids(con, "series", series_ids)
        assert_refs("Release-Series → Series", series_ids, ids_from(series))

        assert_count("releases", len(releases))
        assert_count("castings", len(castings))
        assert_count("series", len(series))
        assert_count("release_series", len(release_series))

        print("\n[4/8] Exporting identifiers")
        release_identifiers = fetch_link_rows(
            con, "release_identifiers", "release_id", release_ids
        )
        identifier_ids = {
            row["identifier_id"]
            for row in release_identifiers
            if row.get("identifier_id") is not None
        }
        catalog_identifiers = fetch_by_ids(
            con, "catalog_identifiers", identifier_ids
        )
        assert_refs(
            "Release identifiers → Catalog identifiers",
            identifier_ids,
            ids_from(catalog_identifiers),
        )

        identifier_type_ids = {
            row["identifier_type_id"]
            for row in catalog_identifiers
            if row.get("identifier_type_id") is not None
        }
        identifier_types = fetch_by_ids(
            con, "identifier_types", identifier_type_ids
        )
        assert_refs(
            "Catalog identifiers → Identifier types",
            identifier_type_ids,
            ids_from(identifier_types),
        )
        assert_count("release_identifiers", len(release_identifiers))

        print("\n[5/8] Exporting Evidence and all Evidence link tables")
        evidence_release_links = fetch_link_rows(
            con, "evidence_releases", "release_id", release_ids
        )
        evidence_ids = {
            row["evidence_id"]
            for row in evidence_release_links
            if row.get("evidence_id") is not None
        }
        evidence = fetch_by_ids(con, "evidence", evidence_ids)
        assert_refs(
            "Evidence-Releases → Evidence",
            evidence_ids,
            ids_from(evidence),
        )

        # Export every discovered Evidence association table for these
        # Evidence IDs, including currently empty tables.
        evidence_links: dict[str, list[dict[str, Any]]] = {}
        for table in EVIDENCE_LINK_TABLES:
            if table not in tables:
                fail(f"Expected Evidence relationship table missing: {table}")

            columns = table_columns(con, table)
            if "evidence_id" not in columns:
                fail(f"{table} no longer has evidence_id.")

            evidence_links[table] = fetch_link_rows(
                con, table, "evidence_id", evidence_ids
            )

        # Ensure each selected Evidence row is represented by its
        # Release relationship and that no unexpected evidence rows
        # have slipped into the selection.
        evidence_release_ids = {
            row["evidence_id"]
            for row in evidence_links["evidence_releases"]
        }
        if evidence_release_ids != evidence_ids:
            fail("Evidence-Releases selection changed during collection.")

        evidence_casting_ids = {
            row["casting_id"]
            for row in evidence_links["evidence_castings"]
            if row.get("casting_id") is not None
        }
        evidence_series_ids = {
            row["series_id"]
            for row in evidence_links["evidence_series"]
            if row.get("series_id") is not None
        }

        assert_refs(
            "Evidence-Castings → selected Castings",
            evidence_casting_ids,
            casting_ids,
        )
        assert_refs(
            "Evidence-Series → exported Series",
            evidence_series_ids,
            series_ids,
        )

        assert_count("evidence", len(evidence))
        assert_count(
            "evidence_releases",
            len(evidence_links["evidence_releases"]),
        )
        assert_count(
            "evidence_castings",
            len(evidence_links["evidence_castings"]),
        )
        assert_count(
            "evidence_series",
            len(evidence_links["evidence_series"]),
        )

        print("\n[6/8] Exporting Source Records and Sources")
        source_record_ids = {
            row["source_record_id"]
            for row in evidence
            if row.get("source_record_id") is not None
        }
        source_records = fetch_by_ids(
            con, "source_records", source_record_ids
        )
        assert_refs(
            "Evidence → Source Records",
            source_record_ids,
            ids_from(source_records),
        )

        source_ids = {
            row["source_id"]
            for row in source_records
            if row.get("source_id") is not None
        }
        sources = fetch_by_ids(con, "sources", source_ids)
        assert_refs(
            "Source Records → Sources",
            source_ids,
            ids_from(sources),
        )
        assert_count("source_records", len(source_records))

        # Preserve the raw_data database value exactly as returned by
        # SQLite. It is intentionally NOT passed through json.loads().

        print("\n[7/8] Building schema inventory and export document")
        schema_inventory = {
            table: table_schema(con, table)
            for table in sorted(tables)
        }

        # Keep all checked auxiliary tables visible in the JSON.
        # They are empty in the inspected database; a non-empty table
        # would have caused a deliberate stop above.
        auxiliary_tables = {
            table: []
            for table in RELATED_TABLES
        }

        export_data = {
            "metadata": {
                "export_type": "mainline_year_catalog",
                "export_version": 3,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "source_database": DB_PATH.name,
                "selection": {
                    "product_line_name": PRODUCT_LINE_NAME,
                    "product_line_type": PRODUCT_LINE_TYPE,
                    "product_line_id": product_line_id,
                    "catalog_year": TARGET_YEAR,
                    "year_node_id": year_node["id"],
                },
                "safety": {
                    "database_open_mode": "ro",
                    "sqlite_query_only": True,
                    "database_writes_performed": False,
                    "raw_data_transformed": False,
                    "normalization_applied": False,
                    "existing_output_overwritten": False,
                },
                "expected_counts": EXPECTED_COUNTS,
                "actual_counts": {},
                "checked_empty_tables": empty_table_counts,
                "notes": [
                    "Catalog tree includes the selected year node, "
                    "all descendants and the complete ancestor chain.",
                    "Source Records raw_data is preserved as its original "
                    "SQLite value without parsing or re-serialization.",
                    "Evidence links are exported by table name.",
                    "Auxiliary tables listed in checked_empty_tables "
                    "were verified empty before export.",
                    "Schema inventory records columns, primary-key "
                    "positions and declared foreign keys.",
                    "Statuses, raw values and source values are not "
                    "normalized or corrected.",
                ],
            },
            "product_lines": [product_line],
            "catalog_tree": catalog_tree,
            "releases": releases,
            "castings": castings,
            "series": series,
            "release_series": release_series,
            "catalog_identifiers": catalog_identifiers,
            "identifier_types": identifier_types,
            "release_identifiers": release_identifiers,
            "sources": sources,
            "source_records": source_records,
            "evidence": evidence,
            "evidence_links": evidence_links,
            "auxiliary_tables": auxiliary_tables,
            "schema_inventory": schema_inventory,
        }

        actual_counts = {
            key: len(value)
            for key, value in export_data.items()
            if isinstance(value, list)
        }
        actual_counts["evidence_link_tables"] = {
            table: len(rows)
            for table, rows in evidence_links.items()
        }
        actual_counts["auxiliary_tables"] = {
            table: len(rows)
            for table, rows in auxiliary_tables.items()
        }
        export_data["metadata"]["actual_counts"] = actual_counts

        print("\n[8/8] Writing JSON without overwriting")
        if OUTPUT_PATH.exists():
            fail(f"Output appeared before writing: {OUTPUT_PATH}")

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        json_text = json.dumps(
            export_data,
            ensure_ascii=False,
            indent=2,
        )

        # Exclusive creation: fails if another file appeared at this path.
        try:
            with OUTPUT_PATH.open("x", encoding="utf-8", newline="\n") as file:
                file.write(json_text)
                file.write("\n")
        except FileExistsError:
            fail(f"Output already exists; no overwrite: {OUTPUT_PATH}")

        try:
            with OUTPUT_PATH.open("r", encoding="utf-8") as file:
                read_back = json.load(file)

            if read_back != export_data:
                fail("JSON read-back validation failed.")
        except Exception:
            # Do not leave a partial or invalid export behind.
            if OUTPUT_PATH.exists():
                OUTPUT_PATH.unlink()
            raise

        print(f"\nSUCCESS: {OUTPUT_PATH}")
        print(f"File size: {OUTPUT_PATH.stat().st_size:,} bytes")
        print("\nExported top-level record counts:")
        for name, count in actual_counts.items():
            print(f"  {name}: {count}")

        print("\nSource database remained read-only.")

    finally:
        con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nEXPORT FAILED")
        print(f"{type(exc).__name__}: {exc}")
        sys.exit(1)

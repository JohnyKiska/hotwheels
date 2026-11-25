"""Add ProductLine, ReleaseProductLine, and EvidenceProductLine tables."""

from alembic import op
import sqlalchemy as sa


revision = "20261123_product_line_tables"
down_revision = "20261123_release_nullable_casting"
branch_labels = None
depends_on = None


TABLE_ORDER = (
    "product_lines",
    "release_product_lines",
    "evidence_product_lines",
)

EXPECTED_COLUMNS = {
    "product_lines": (
        ("id", sa.String(36), False),
        ("code", sa.String(80), False),
        ("name", sa.String(240), False),
        ("normalized_name", sa.String(240), False),
        ("description", sa.Text(), True),
        ("parent_product_line_id", sa.String(36), True),
        ("status", sa.String(24), False),
        ("created_at", sa.DateTime(timezone=True), False),
        ("updated_at", sa.DateTime(timezone=True), False),
    ),
    "release_product_lines": (
        ("id", sa.String(36), False),
        ("release_id", sa.String(36), False),
        ("product_line_id", sa.String(36), False),
        ("membership_status", sa.String(24), False),
        ("created_at", sa.DateTime(timezone=True), False),
        ("updated_at", sa.DateTime(timezone=True), False),
    ),
    "evidence_product_lines": (
        ("evidence_id", sa.String(36), False),
        ("release_product_line_id", sa.String(36), False),
        ("role", sa.String(32), False),
        ("note", sa.Text(), True),
    ),
}

EXPECTED_PRIMARY_KEYS = {
    "product_lines": ("id",),
    "release_product_lines": ("id",),
    "evidence_product_lines": ("evidence_id", "release_product_line_id"),
}

EXPECTED_UNIQUE_CONSTRAINTS = {
    "product_lines": {
        ("uq_product_lines_code", ("code",)),
        ("uq_product_lines_normalized_name", ("normalized_name",)),
    },
    "release_product_lines": {
        ("uq_release_product_lines_pair", ("release_id", "product_line_id")),
    },
    "evidence_product_lines": set(),
}

EXPECTED_CHECK_CONSTRAINTS = {
    "product_lines": {
        (
            "ck_product_lines_status",
            "status IN ('candidate', 'under_review', 'confirmed', 'rejected')",
        ),
        (
            "ck_product_lines_not_own_parent",
            "parent_product_line_id IS NULL OR parent_product_line_id != id",
        ),
    },
    "release_product_lines": {
        (
            "ck_release_product_lines_membership_status",
            "membership_status IN ('active', 'withdrawn')",
        ),
    },
    "evidence_product_lines": set(),
}

EXPECTED_FOREIGN_KEYS = {
    "product_lines": {
        (("parent_product_line_id",), "product_lines", ("id",), "RESTRICT"),
    },
    "release_product_lines": {
        (("release_id",), "releases", ("id",), "RESTRICT"),
        (("product_line_id",), "product_lines", ("id",), "RESTRICT"),
    },
    "evidence_product_lines": {
        (("evidence_id",), "evidence", ("id",), "CASCADE"),
        (
            ("release_product_line_id",),
            "release_product_lines",
            ("id",),
            "RESTRICT",
        ),
    },
}

EXPECTED_INDEXES = {
    "product_lines": {
        ("ix_product_lines_parent_product_line_id", ("parent_product_line_id",), False),
    },
    "release_product_lines": {
        (
            "ix_release_product_lines_product_line_id",
            ("product_line_id",),
            False,
        ),
    },
    "evidence_product_lines": {
        (
            "ix_evidence_product_lines_release_product_line_id",
            ("release_product_line_id",),
            False,
        ),
    },
}


def _type_name(column_type, bind):
    return column_type.compile(dialect=bind.dialect).upper()


def _check_schema(bind, table_name):
    inspector = sa.inspect(bind)
    mismatches = []

    actual_columns = {
        column["name"]: (
            _type_name(column["type"], bind),
            column["nullable"],
            column["default"],
        )
        for column in inspector.get_columns(table_name)
    }
    expected_columns = {
        name: (_type_name(column_type, bind), nullable, None)
        for name, column_type, nullable in EXPECTED_COLUMNS[table_name]
    }
    if actual_columns != expected_columns:
        mismatches.append("columns")

    actual_primary_key = tuple(
        inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
    )
    if actual_primary_key != EXPECTED_PRIMARY_KEYS[table_name]:
        mismatches.append("primary key")

    actual_unique_constraints = {
        (constraint.get("name"), tuple(constraint["column_names"]))
        for constraint in inspector.get_unique_constraints(table_name)
    }
    if actual_unique_constraints != EXPECTED_UNIQUE_CONSTRAINTS[table_name]:
        mismatches.append("unique constraints")

    actual_check_constraints = {
        (
            constraint.get("name"),
            " ".join(constraint["sqltext"].split()),
        )
        for constraint in inspector.get_check_constraints(table_name)
    }
    if actual_check_constraints != EXPECTED_CHECK_CONSTRAINTS[table_name]:
        mismatches.append("check constraints")

    actual_foreign_keys = {
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
            (foreign_key.get("options") or {}).get("ondelete", "").upper(),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    if actual_foreign_keys != EXPECTED_FOREIGN_KEYS[table_name]:
        mismatches.append("foreign keys")

    actual_indexes = {
        (
            index["name"],
            tuple(index["column_names"]),
            bool(index["unique"]),
        )
        for index in inspector.get_indexes(table_name)
    }
    if actual_indexes != EXPECTED_INDEXES[table_name]:
        mismatches.append("indexes")

    if mismatches:
        raise RuntimeError(
            f"ProductLine migration found incompatible existing table "
            f"'{table_name}': {', '.join(mismatches)} do not match the "
            "expected ProductLine ORM schema."
        )


def _check_foreign_keys(bind):
    if bind.dialect.name != "sqlite":
        return

    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
        raise RuntimeError(
            "ProductLine migration requires SQLite foreign-key enforcement."
        )

    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            f"Foreign key violations detected after ProductLine migration: {violations}"
        )


def _create_product_lines():
    op.create_table(
        "product_lines",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("normalized_name", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_product_line_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('candidate', 'under_review', 'confirmed', 'rejected')",
            name="ck_product_lines_status",
        ),
        sa.CheckConstraint(
            "parent_product_line_id IS NULL OR parent_product_line_id != id",
            name="ck_product_lines_not_own_parent",
        ),
        sa.ForeignKeyConstraint(
            ["parent_product_line_id"],
            ["product_lines.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_product_lines_code"),
        sa.UniqueConstraint(
            "normalized_name", name="uq_product_lines_normalized_name"
        ),
    )
    op.create_index(
        "ix_product_lines_parent_product_line_id",
        "product_lines",
        ["parent_product_line_id"],
        unique=False,
    )


def _create_release_product_lines():
    op.create_table(
        "release_product_lines",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("product_line_id", sa.String(36), nullable=False),
        sa.Column("membership_status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "membership_status IN ('active', 'withdrawn')",
            name="ck_release_product_lines_membership_status",
        ),
        sa.ForeignKeyConstraint(
            ["product_line_id"],
            ["product_lines.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_id",
            "product_line_id",
            name="uq_release_product_lines_pair",
        ),
    )
    op.create_index(
        "ix_release_product_lines_product_line_id",
        "release_product_lines",
        ["product_line_id"],
        unique=False,
    )


def _create_evidence_product_lines():
    op.create_table(
        "evidence_product_lines",
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.Column("release_product_line_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_product_line_id"],
            ["release_product_lines.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evidence_id", "release_product_line_id"),
    )
    op.create_index(
        "ix_evidence_product_lines_release_product_line_id",
        "evidence_product_lines",
        ["release_product_line_id"],
        unique=False,
    )


def upgrade():
    bind = op.get_bind()
    _check_foreign_keys(bind)

    existing_tables = set(sa.inspect(bind).get_table_names())
    for table_name in TABLE_ORDER:
        if table_name in existing_tables:
            _check_schema(bind, table_name)

    if "product_lines" not in existing_tables:
        _create_product_lines()
    if "release_product_lines" not in existing_tables:
        _create_release_product_lines()
    if "evidence_product_lines" not in existing_tables:
        _create_evidence_product_lines()

    for table_name in TABLE_ORDER:
        _check_schema(bind, table_name)
    _check_foreign_keys(bind)


def downgrade():
    bind = op.get_bind()
    _check_foreign_keys(bind)

    existing_tables = set(sa.inspect(bind).get_table_names())
    missing_tables = [name for name in TABLE_ORDER if name not in existing_tables]
    if missing_tables:
        raise RuntimeError(
            "Cannot downgrade ProductLine migration: expected tables are missing: "
            + ", ".join(missing_tables)
        )

    for table_name in TABLE_ORDER:
        _check_schema(bind, table_name)

    populated_tables = []
    for table_name in TABLE_ORDER:
        row_count = bind.execute(
            sa.text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).scalar_one()
        if row_count:
            populated_tables.append(f"{table_name} ({row_count})")

    if populated_tables:
        raise RuntimeError(
            "Cannot downgrade ProductLine migration while data exists in: "
            + ", ".join(populated_tables)
            + ". Remove or archive the ProductLine data explicitly first."
        )

    for table_name in reversed(TABLE_ORDER):
        op.drop_table(table_name)

    _check_foreign_keys(bind)

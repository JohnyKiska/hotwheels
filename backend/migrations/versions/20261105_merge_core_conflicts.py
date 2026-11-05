"""Merge the restored core-schema and conflict-release migration histories.

The catalog schema history and the conflict-release history both descend from
the append-only change-log migration. This no-op revision joins those branches
without rewriting either migration's ancestry.
"""

revision = "20261105_merge_core_conflicts"
down_revision = ("20261030_core_schema", "20261104_conflict_releases")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

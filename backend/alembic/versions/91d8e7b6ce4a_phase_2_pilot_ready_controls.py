"""phase 2 pilot ready controls

Revision ID: 91d8e7b6ce4a
Revises: 4a9c8d2e5f71
Create Date: 2026-04-22 12:00:00.000000

"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "91d8e7b6ce4a"
down_revision: Union[str, Sequence[str], None] = "4a9c8d2e5f71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SYSTEM_ROLES = {
    "admin": "Full administrative access across users, connectors, jobs, and audit logs.",
    "operator": "Can manage owned connectors, review jobs, reindex documents, and use chat.",
    "viewer": "Read-only access for visible documents and grounded chat.",
}


def upgrade() -> None:
    op.add_column("connectors", sa.Column("owner_user_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_connectors_owner_user_id"), "connectors", ["owner_user_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_connectors_owner_user_id_users"),
        "connectors",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    roles = sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.UUID()),
        sa.Column("name", sa.String(length=100)),
        sa.Column("description", sa.Text()),
        sa.Column("is_system", sa.Boolean()),
    )
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.UUID()),
        sa.Column("auth_provider", sa.String(length=50)),
        sa.Column("is_superuser", sa.Boolean()),
        sa.Column("role_id", sa.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    connectors = sa.Table(
        "connectors",
        metadata,
        sa.Column("id", sa.UUID()),
        sa.Column("owner_user_id", sa.UUID()),
    )

    existing_role_names = {
        row[0] for row in bind.execute(sa.select(roles.c.name)).fetchall()
    }
    for name, description in SYSTEM_ROLES.items():
        if name in existing_role_names:
            bind.execute(
                sa.update(roles)
                .where(roles.c.name == name)
                .values(description=description, is_system=True)
            )
            continue
        bind.execute(
            sa.insert(roles).values(
                id=uuid.uuid4(),
                name=name,
                description=description,
                is_system=True,
            )
        )

    role_ids = {
        row.name: row.id
        for row in bind.execute(sa.select(roles.c.id, roles.c.name)).fetchall()
    }

    if "admin" in role_ids:
        bind.execute(
            sa.update(users)
            .where(users.c.role_id.is_(None), users.c.is_superuser.is_(True))
            .values(role_id=role_ids["admin"])
        )
    if "operator" in role_ids:
        bind.execute(
            sa.update(users)
            .where(
                users.c.role_id.is_(None),
                users.c.is_superuser.is_(False),
                users.c.auth_provider == "local",
            )
            .values(role_id=role_ids["operator"])
        )
    if "viewer" in role_ids:
        bind.execute(
            sa.update(users)
            .where(users.c.role_id.is_(None))
            .values(role_id=role_ids["viewer"])
        )

    admin_user_id = bind.execute(
        sa.select(users.c.id)
        .where(users.c.is_superuser.is_(True))
        .order_by(users.c.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if admin_user_id is not None:
        bind.execute(
            sa.update(connectors)
            .where(connectors.c.owner_user_id.is_(None))
            .values(owner_user_id=admin_user_id)
        )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_connectors_owner_user_id_users"), "connectors", type_="foreignkey")
    op.drop_index(op.f("ix_connectors_owner_user_id"), table_name="connectors")
    op.drop_column("connectors", "owner_user_id")

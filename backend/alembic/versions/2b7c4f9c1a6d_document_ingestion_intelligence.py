"""document ingestion intelligence metadata

Revision ID: 2b7c4f9c1a6d
Revises: 9c0f715215f5
Create Date: 2026-04-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "2b7c4f9c1a6d"
down_revision: Union[str, Sequence[str], None] = "9c0f715215f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("file_extension", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("source_type", sa.String(length=50), server_default="nextcloud", nullable=False))
    op.add_column("documents", sa.Column("language", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("word_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("token_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.add_column("documents", sa.Column("permission_scope", sa.String(length=100), nullable=True))
    op.add_column("documents", sa.Column("intelligence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("documents", sa.Column("ingestion_events_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("documents", sa.Column("document_type", sa.String(length=100), server_default="unclassified", nullable=False))
    op.add_column("documents", sa.Column("document_type_confidence", sa.Float(), server_default="0", nullable=False))
    op.add_column("documents", sa.Column("document_type_reason", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("document_type_source", sa.String(length=20), server_default="fallback", nullable=False))
    op.add_column("documents", sa.Column("business_domain", sa.String(length=100), server_default="unknown", nullable=False))
    op.add_column("documents", sa.Column("business_domain_confidence", sa.Float(), server_default="0", nullable=False))
    op.add_column("documents", sa.Column("business_domain_reason", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("business_domain_source", sa.String(length=20), server_default="fallback", nullable=False))
    op.add_column("documents", sa.Column("manual_category_override", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("document_chunks", sa.Column("chunk_type", sa.String(length=50), server_default="text", nullable=False))
    op.add_column("document_chunks", sa.Column("embedding_status", sa.String(length=50), server_default="pending", nullable=False))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(length=255), nullable=True))
    op.create_foreign_key(op.f("fk_documents_owner_id_users"), "documents", "users", ["owner_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_documents_file_extension", "documents", ["file_extension"], unique=False)
    op.create_index("ix_documents_document_type", "documents", ["document_type"], unique=False)
    op.create_index("ix_documents_business_domain", "documents", ["business_domain"], unique=False)
    op.create_index("ix_documents_parse_status", "documents", ["parse_status"], unique=False)
    op.create_index("ix_documents_source_type", "documents", ["source_type"], unique=False)
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"], unique=False)
    op.create_index("ix_document_chunks_embedding_status", "document_chunks", ["embedding_status"], unique=False)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_fts "
        "ON document_chunks USING gin (to_tsvector('simple', content))"
    )
    op.alter_column("documents", "connector_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("documents", "external_id", existing_type=sa.String(length=512), nullable=True)
    op.execute("UPDATE documents SET file_extension = lower(regexp_replace(file_name, '^.*(\\.[^.]+)$', '\\1')) WHERE file_name LIKE '%.%'")
    op.execute("UPDATE documents SET source_type = 'nextcloud' WHERE source_type IS NULL")


def downgrade() -> None:
    op.alter_column("documents", "external_id", existing_type=sa.String(length=512), nullable=False)
    op.alter_column("documents", "connector_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index("ix_document_chunks_embedding_status", table_name="document_chunks")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_fts")
    op.drop_index("ix_documents_owner_id", table_name="documents")
    op.drop_index("ix_documents_source_type", table_name="documents")
    op.drop_index("ix_documents_parse_status", table_name="documents")
    op.drop_index("ix_documents_business_domain", table_name="documents")
    op.drop_index("ix_documents_document_type", table_name="documents")
    op.drop_index("ix_documents_file_extension", table_name="documents")
    op.drop_constraint(op.f("fk_documents_owner_id_users"), "documents", type_="foreignkey")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding_status")
    op.drop_column("document_chunks", "chunk_type")
    op.drop_column("documents", "manual_category_override")
    op.drop_column("documents", "business_domain_source")
    op.drop_column("documents", "business_domain_reason")
    op.drop_column("documents", "business_domain_confidence")
    op.drop_column("documents", "business_domain")
    op.drop_column("documents", "document_type_source")
    op.drop_column("documents", "document_type_reason")
    op.drop_column("documents", "document_type_confidence")
    op.drop_column("documents", "document_type")
    op.drop_column("documents", "ingestion_events_json")
    op.drop_column("documents", "intelligence_json")
    op.drop_column("documents", "permission_scope")
    op.drop_column("documents", "owner_id")
    op.drop_column("documents", "classified_at")
    op.drop_column("documents", "token_count")
    op.drop_column("documents", "word_count")
    op.drop_column("documents", "page_count")
    op.drop_column("documents", "language")
    op.drop_column("documents", "source_type")
    op.drop_column("documents", "file_extension")

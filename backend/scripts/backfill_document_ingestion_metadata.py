from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from backend.db.models import Document
from backend.db.session import AsyncSessionLocal
from backend.ingestion.classifier import rule_classify
from backend.parsers.document_parser import ParsedDocument, ParsedPage


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Document))
        documents = list(result.scalars().all())
        for document in documents:
            metadata = dict(document.metadata_json or {})
            text = str(metadata.get("text_preview") or document.file_name or "")
            parsed = ParsedDocument(
                text=text,
                pages=[ParsedPage(page_number=None, text=text)] if text else [],
                metadata=metadata,
            )
            classification = rule_classify(document=document, parsed=parsed)
            if not document.manual_category_override:
                document.document_type = classification.document_type
                document.document_type_confidence = min(classification.document_type_confidence, 0.6)
                document.document_type_reason = f"Backfill: {classification.document_type_reason}"
                document.document_type_source = classification.document_type_source
                document.business_domain = classification.business_domain
                document.business_domain_confidence = min(classification.business_domain_confidence, 0.6)
                document.business_domain_reason = f"Backfill: {classification.business_domain_reason}"
                document.business_domain_source = classification.business_domain_source
            document.file_extension = document.file_extension or Path(document.file_name).suffix.lower() or None
            document.source_type = document.source_type or "nextcloud"
            document.permission_scope = document.permission_scope or "connector"
        await session.commit()
        print(f"Backfilled {len(documents)} documents without deleting chunks.")


if __name__ == "__main__":
    asyncio.run(main())


"""Evaluate the supported child/overlap grid on the isolated gold corpus."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from ..parsers.document_parser import ParsedDocument, ParsedPage
from ..rag.chunker import (
    CHILD_CHUNK_SIZE_GRID,
    CHILD_OVERLAP_GRID,
    HeadingTableAwareChunker,
    RagChunkDraft,
    build_parent_chunks,
)
from ..rag.parser import RagParser
from .fixture_loader import documents_visible_to, load_fixture_bundle, resolve_ids
from .offline_scorer import mean_metrics, score_retrieval
from .run_offline_eval import _default_identity, _tokenize


@dataclass(frozen=True, slots=True)
class ChunkGridResult:
    child_size: int
    overlap: int
    child_count: int
    parent_count: int
    duplicate_count: int
    oversized_count: int
    recall_at_3: float
    recall_at_6: float
    mrr: float
    ndcg_at_6: float


def evaluate_chunk_grid() -> list[ChunkGridResult]:
    bundle = load_fixture_bundle()
    results: list[ChunkGridResult] = []
    for child_size in CHILD_CHUNK_SIZE_GRID:
        for overlap in CHILD_OVERLAP_GRID:
            if overlap >= child_size:
                continue
            chunker = HeadingTableAwareChunker(
                chunk_size=child_size,
                overlap=overlap,
            )
            chunks_by_document: dict[str, list[RagChunkDraft]] = {}
            child_count = 0
            parent_count = 0
            duplicate_count = 0
            oversized_count = 0
            for document in bundle.documents:
                pages = [
                    ParsedPage(page_number=chunk.page_number or 1, text=chunk.text)
                    for chunk in document.chunks
                ]
                if document.key == "handbook_multipage":
                    # A deterministic long-page probe makes size/overlap effects
                    # observable even though the human-readable fixture is small.
                    pages.append(
                        ParsedPage(
                            page_number=10,
                            text=" ".join(
                                f"operational-procedure-{index % 37}"
                                for index in range(720)
                            ),
                        )
                    )
                parsed = ParsedDocument(
                    text="\n\n".join(page.text for page in pages),
                    pages=pages,
                    metadata={"fixture_key": document.key},
                )
                children = chunker.chunk(RagParser().normalize(parsed))
                chunks_by_document[document.key] = list(children)
                child_count += len(children)
                parent_count += len(
                    build_parent_chunks(children, child_size=child_size)
                )
                duplicate_count += len(children) - len(
                    {chunk.content for chunk in children}
                )
                oversized_count += sum(
                    1 for chunk in children if chunk.token_count > child_size
                )

            case_metrics: list[dict[str, float]] = []
            for row in bundle.gold:
                identity = _default_identity(bundle, row)
                visible = documents_visible_to(bundle, identity.key)
                explicit_scope = set(resolve_ids(row.request_document_ids))
                question_tokens = _tokenize(row.question)
                ranking: list[tuple[int, str]] = []
                for document in visible:
                    document_id = str(document.document_id)
                    if explicit_scope and document_id not in explicit_scope:
                        continue
                    best_overlap = max(
                        (
                            len(question_tokens & _tokenize(chunk.content))
                            for chunk in chunks_by_document[document.key]
                        ),
                        default=0,
                    )
                    if best_overlap:
                        ranking.append((best_overlap, document_id))
                ranking.sort(key=lambda item: (-item[0], item[1]))
                expected_ids = resolve_ids(row.expected_document_ids)
                if expected_ids:
                    case_metrics.append(
                        score_retrieval(
                            expected_ids=expected_ids,
                            retrieved_ids=[
                                document_id for _, document_id in ranking[:6]
                            ],
                            unit="document",
                        )
                    )
            means = mean_metrics(
                case_metrics,
                ["recall@3", "recall@6", "mrr", "ndcg@6"],
            )
            results.append(
                ChunkGridResult(
                    child_size=child_size,
                    overlap=overlap,
                    child_count=child_count,
                    parent_count=parent_count,
                    duplicate_count=duplicate_count,
                    oversized_count=oversized_count,
                    recall_at_3=means["recall@3"],
                    recall_at_6=means["recall@6"],
                    mrr=means["mrr"],
                    ndcg_at_6=means["ndcg@6"],
                )
            )
    return results


def main() -> int:
    results = evaluate_chunk_grid()
    ranked = sorted(
        results,
        key=lambda item: (
            -item.recall_at_6,
            -item.mrr,
            item.oversized_count,
            item.duplicate_count,
            item.child_count,
            item.child_size,
            item.overlap,
        ),
    )
    print(
        json.dumps(
            {
                "recommended": asdict(ranked[0]) if ranked else None,
                "results": [asdict(result) for result in results],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ranked and not ranked[0].oversized_count else 1


if __name__ == "__main__":
    raise SystemExit(main())

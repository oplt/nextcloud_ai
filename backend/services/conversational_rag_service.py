from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol
from uuid import UUID, uuid4

from ..ai.prompt_builder import GROUNDED_PROMPT_VERSION
from ..schemas.chat_schema import (
    ChatAskRequest,
    ChatAskResponse,
    ChatSource,
    ChatTurn,
    ConversationState,
    GroundedChunk,
)


@dataclass(slots=True)
class RetrievalCandidate:
    chunk: GroundedChunk
    retrieval_score: float
    retrieval_distance: float


class HistoryStore(Protocol):
    def get_turns(self, session_id: str, limit: int = 8) -> list[ChatTurn]: ...
    def load_state(self, session_id: str) -> ConversationState | None: ...
    def save_state(self, state: ConversationState) -> None: ...


class QueryRewriter(Protocol):
    def rewrite(
        self,
        question: str,
        history: list[ChatTurn],
        active_document_ids: list[str],
    ) -> str: ...


class Retriever(Protocol):
    def search(
        self,
        query: str,
        *,
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[RetrievalCandidate]: ...


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]: ...


class AnswerGenerator(Protocol):
    def answer(
        self,
        question: str,
        conversation_query: str,
        history: list[ChatTurn],
        grounded_chunks: list[GroundedChunk],
    ) -> tuple[str, list[str]]: ...


@dataclass(slots=True)
class ConversationalRagConfig:
    top_k: int = 6
    focused_search_k: int = 10
    broaden_search_k: int = 12
    max_grounded_chunks: int = 4
    minimum_score: float = 0.45
    focused_confidence_threshold: float = 0.72
    topic_shift_lexical_overlap_threshold: float = 0.18


class ConversationalRagService:
    def __init__(
        self,
        *,
        history_store: HistoryStore,
        query_rewriter: QueryRewriter,
        retriever: Retriever,
        reranker: Reranker,
        answer_generator: AnswerGenerator,
        config: ConversationalRagConfig | None = None,
    ) -> None:
        self.history_store = history_store
        self.query_rewriter = query_rewriter
        self.retriever = retriever
        self.reranker = reranker
        self.answer_generator = answer_generator
        self.config = config or ConversationalRagConfig()

    def answer(self, request: ChatAskRequest) -> ChatAskResponse:
        session_id = request.session_id or str(uuid4())
        history = self.history_store.get_turns(session_id, limit=8) if request.session_id else []
        prior_state = self.history_store.load_state(session_id) or ConversationState(session_id=session_id)
        active_document_ids = self._merge_active_document_ids(
            request.active_context_document_ids,
            prior_state.active_document_ids,
        )

        conversation_query = self.query_rewriter.rewrite(
            request.question,
            history,
            active_document_ids,
        )

        candidates = self._retrieve_candidates(
            question=request.question,
            conversation_query=conversation_query,
            active_document_ids=active_document_ids,
        )
        grounded_chunks = self._select_grounded_chunks(candidates)

        answer_text, cited_chunk_ids = self.answer_generator.answer(
            request.question,
            conversation_query,
            history,
            grounded_chunks,
        )

        cited_sources = self._build_cited_sources(grounded_chunks, cited_chunk_ids)
        if not cited_sources:
            cited_sources = [chunk.as_source() for chunk in grounded_chunks]

        new_state = ConversationState(
            session_id=session_id,
            active_document_ids=self._ranked_document_ids_from_sources(cited_sources),
            last_cited_chunk_ids=[source.chunk_id for source in cited_sources],
            retrieval_summary=conversation_query,
            topic_fingerprint=self._topic_fingerprint(conversation_query),
        )
        self.history_store.save_state(new_state)

        active_context_documents = [
            {
                'document_id': source.document_id,
                'file_name': source.file_name,
                'file_path': source.file_path,
            }
            for source in self._dedupe_sources_by_document(cited_sources)
        ]

        trace_id = request.request_id or str(uuid4())
        session_uuid = session_id if isinstance(session_id, UUID) else UUID(str(session_id))
        return ChatAskResponse(
            session_id=session_uuid,
            answer=answer_text,
            user_message_id=uuid4(),
            assistant_message_id=uuid4(),
            parent_message_id=request.parent_message_id,
            request_id=request.request_id,
            sources=[candidate.chunk.as_source() for candidate in candidates],
            cited_sources=cited_sources,
            active_context_document_ids=new_state.active_document_ids,
            active_context_documents=active_context_documents,
            conversation_query=conversation_query,
            generation_trace_id=trace_id,
            llm_provider='conversational_rag',
            llm_model_id='local',
            grounded_prompt_version=GROUNDED_PROMPT_VERSION,
            retrieval_settings={'pipeline': 'conversational_rag', 'top_k': self.config.top_k},
            verification=None,
        )

    def _retrieve_candidates(
        self,
        *,
        question: str,
        conversation_query: str,
        active_document_ids: list[str],
    ) -> list[RetrievalCandidate]:
        focused_candidates: list[RetrievalCandidate] = []
        if active_document_ids and not self._looks_like_topic_shift(question, conversation_query):
            focused_candidates = self.retriever.search(
                conversation_query,
                top_k=self.config.focused_search_k,
                document_ids=active_document_ids,
            )
            focused_candidates = self.reranker.rerank(conversation_query, focused_candidates)
            focused_confidence = focused_candidates[0].chunk.score if focused_candidates else 0.0
            if focused_confidence >= self.config.focused_confidence_threshold:
                return focused_candidates

        broadened_candidates = self.retriever.search(
            conversation_query,
            top_k=self.config.broaden_search_k,
            document_ids=None,
        )
        merged_candidates = self._merge_candidate_lists(focused_candidates, broadened_candidates)
        return self.reranker.rerank(conversation_query, merged_candidates)

    def _select_grounded_chunks(self, candidates: list[RetrievalCandidate]) -> list[GroundedChunk]:
        grounded: list[GroundedChunk] = []
        seen_chunk_ids: set[str] = set()

        for candidate in candidates:
            chunk = candidate.chunk
            if chunk.chunk_id in seen_chunk_ids:
                continue
            if chunk.score < self.config.minimum_score:
                continue
            grounded.append(chunk)
            seen_chunk_ids.add(chunk.chunk_id)
            if len(grounded) >= self.config.max_grounded_chunks:
                break

        return grounded

    def _build_cited_sources(
        self,
        grounded_chunks: list[GroundedChunk],
        cited_chunk_ids: list[str],
    ) -> list[ChatSource]:
        if not grounded_chunks:
            return []

        by_chunk_id = {chunk.chunk_id: chunk for chunk in grounded_chunks}
        cited_sources: list[ChatSource] = []
        for chunk_id in cited_chunk_ids:
            chunk = by_chunk_id.get(chunk_id)
            if chunk:
                cited_sources.append(chunk.as_source())
        return cited_sources

    def _merge_candidate_lists(
        self,
        focused: list[RetrievalCandidate],
        broadened: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        by_chunk_id: dict[str, RetrievalCandidate] = {}
        for candidate in [*focused, *broadened]:
            existing = by_chunk_id.get(candidate.chunk.chunk_id)
            if existing is None or candidate.chunk.score > existing.chunk.score:
                by_chunk_id[candidate.chunk.chunk_id] = candidate
        return list(by_chunk_id.values())

    def _merge_active_document_ids(self, requested: list[str], stateful: list[str]) -> list[str]:
        combined: list[str] = []
        for document_id in [*requested, *stateful]:
            if document_id and document_id not in combined:
                combined.append(document_id)
        return combined

    def _ranked_document_ids_from_sources(self, sources: Iterable[ChatSource]) -> list[str]:
        ranked: list[str] = []
        for source in sources:
            if source.document_id not in ranked:
                ranked.append(source.document_id)
        return ranked

    def _dedupe_sources_by_document(self, sources: Iterable[ChatSource]) -> list[ChatSource]:
        by_document: dict[str, ChatSource] = {}
        for source in sources:
            current = by_document.get(source.document_id)
            if current is None or source.score > current.score:
                by_document[source.document_id] = source
        return list(by_document.values())

    def _looks_like_topic_shift(self, question: str, conversation_query: str) -> bool:
        question_terms = {token for token in question.lower().split() if len(token) > 2}
        query_terms = {token for token in conversation_query.lower().split() if len(token) > 2}
        if not question_terms or not query_terms:
            return False
        overlap = len(question_terms & query_terms) / max(len(question_terms), 1)
        return overlap < self.config.topic_shift_lexical_overlap_threshold

    def _topic_fingerprint(self, text: str) -> str:
        return '|'.join(sorted({token for token in text.lower().split() if len(token) > 3})[:12])

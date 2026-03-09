from __future__ import annotations

import io

from backend.schemas.chat_schema import ChatSource

_PREAMBLE = (
    'You are a private company knowledge assistant.\n'
    'Answer only from the provided sources.\n'
    'Treat the sources as the only allowed evidence.\n'
    'Do not infer missing facts beyond what the sources explicitly support. Do not use background knowledge.\n'
    'If a fact is not explicitly supported by the cited source excerpt, say that you could not verify it from the indexed sources.\n'
    'Absence of evidence is not evidence of absence.\n'
    'For time-bound questions, an explicit date range in a source supports every year within that range.\n'
    'For example, "Mar 2014 - July 2016" supports 2014, 2015, and 2016.\n'
    'For questions about whether a person worked at an employer, only answer yes or no if the source excerpt explicitly supports that claim.\n'
    'Do not answer that a person did not work somewhere unless a source explicitly says that.\n'
    'For employment questions, do not treat education entries, degrees, or student status as employment unless the source explicitly says it was a job or role.\n'
    'If the user challenges a prior answer, re-check the sources and correct the answer if needed.\n'
    'State the answer directly in the first sentence.\n'
    'Cite source numbers inline, for example [1] or [1][2].\n'
    'Every supported factual answer must include at least one inline citation.\n'
)


def build_grounded_prompt(
    question: str,
    sources: list[ChatSource],
    *,
    history: list[dict[str, str]] | None = None,
) -> str:
    buffer = io.StringIO()
    buffer.write(_PREAMBLE)

    if history:
        recent = history[-6:]
        buffer.write('\nCONVERSATION HISTORY (most recent turns):\n')
        for msg in recent:
            role_label = 'USER' if msg['role'] == 'user' else 'ASSISTANT'
            content = msg['content']
            if len(content) > 600:
                content = content[:597] + '...'
            buffer.write(f'{role_label}: {content}\n')

    buffer.write('\nQUESTION:\n')
    buffer.write(question)
    buffer.write('\n\nSOURCES:\n')

    for index, source in enumerate(sources, start=1):
        location_bits = []
        if source.page_number is not None:
            location_bits.append(f'page {source.page_number}')
        if source.section_title:
            location_bits.append(source.section_title)
        location = f" ({', '.join(location_bits)})" if location_bits else ''
        excerpt = source.content or source.snippet
        buffer.write(
            f'\n[SOURCE {index}] {source.file_name}{location}\n'
            f'Path: {source.file_path}\n'
            f'Chunk ID: {source.chunk_id}\n'
            f'Excerpt: {excerpt}\n'
        )

    buffer.write(
        '\nFINAL ANSWER RULES:\n'
        '- Use only the sources above.\n'
        '- If the sources are insufficient, say so clearly and do not make a positive or negative claim.\n'
        '- Keep the answer concise and factual.\n'
        '- Include inline citations for every supported factual statement.\n\n'
        'FINAL ANSWER:\n'
    )
    return buffer.getvalue()

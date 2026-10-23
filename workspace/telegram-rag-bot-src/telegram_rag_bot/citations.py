"""Quote only a nonempty document from the caller's already-used RAG context."""
from dataclasses import dataclass
from langchain_core.documents import Document
from telegram_rag_bot.i18n import t


@dataclass(frozen=True)
class Citation:
    source_display: str
    quote: str


def extract_citation(context: list[Document], allowed_titles: dict[str, str]) -> Citation | None:
    """Return exact full page_content: no query or expected-fact contract exists.

    A caller supplies only context actually used to answer. Unknown/missing sources
    or empty pages cannot establish provenance and produce None. No retrieval occurs.
    """
    for doc in context:
        source = doc.metadata.get('source')
        if not isinstance(source, str) or source not in allowed_titles:
            continue
        title = allowed_titles[source]
        if not isinstance(title, str) or not title.strip() or not isinstance(doc.page_content, str) or not doc.page_content.strip():
            continue
        try:
            display = t(title)
        except (KeyError, RuntimeError, ValueError):
            display = title
        return Citation(source_display=display, quote=doc.page_content)
    return None

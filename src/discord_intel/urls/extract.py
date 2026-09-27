"""Extract URL occurrences while retaining their exact message spans."""

from dataclasses import dataclass

from linkify_it import LinkifyIt  # type: ignore[import-untyped]

_LINKIFY = LinkifyIt().set({"fuzzy_link": False, "fuzzy_email": False})

@dataclass(frozen=True, slots=True)
class URLOccurrence:
    """An original HTTP(S) URL and its half-open character span in message content."""

    raw_url: str
    start_offset: int
    end_offset: int


def extract_urls(content: str) -> list[URLOccurrence]:
    """Return every HTTP(S) URL occurrence in source order without surrounding punctuation."""
    occurrences: list[URLOccurrence] = []
    for match in _LINKIFY.match(content) or []:
        if match.schema.lower() not in {"http:", "https:"}:
            continue
        start = match.index
        end = match.last_index
        occurrences.append(
            URLOccurrence(
                raw_url=content[start:end],
                start_offset=start,
                end_offset=end,
            )
        )
    return occurrences
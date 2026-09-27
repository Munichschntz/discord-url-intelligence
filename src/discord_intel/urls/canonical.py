"""Conservative HTTP(S) URL canonicalization and provider classification."""

import re
from dataclasses import dataclass
from urllib.parse import SplitResult, unquote_plus, urlsplit, urlunsplit

from url_normalize import url_normalize

_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_TRACKING_KEYS = frozenset({"fbclid", "gclid"})


@dataclass(frozen=True, slots=True)
class CanonicalURL:
    """Canonical identity and provider hints for one original URL."""

    canonical_url: str
    host: str
    domain: str
    provider: str | None = None
    resource_type: str | None = None
    provider_repo: str | None = None


def _without_tracking_parameters(query: str) -> str:
    if not query:
        return query
    retained: list[str] = []
    for component in query.split("&"):
        key = unquote_plus(component.partition("=")[0]).casefold()
        if key.startswith("utm_") or key in _TRACKING_KEYS:
            continue
        retained.append(component)
    return "&".join(retained)


def _provider_identity(
    host: str, path: str
) -> tuple[str | None, str | None, str | None, str]:
    if host == "github.com":
        segments = path.lstrip("/").split("/") if path.startswith("/") else []
        if len(segments) >= 2 and all(segments[:2]):
            owner, repository = segments[0].lower(), segments[1].lower()
            provider_repo = f"{owner}/{repository}"
            tail = segments[2:]
            if not tail or tail == [""]:
                return "github", "repository", provider_repo, f"/{owner}/{repository}"
            normalized_path = "/" + "/".join([owner, repository, *tail])
            return "github", "repository_page", provider_repo, normalized_path
        return "github", "profile_or_page", None, path

    if host == "huggingface.co":
        segments = path.lstrip("/").split("/") if path.startswith("/") else []
        resource_type = "model"
        root_length = 2
        if segments and segments[0] in {"datasets", "spaces"}:
            resource_type = "dataset" if segments[0] == "datasets" else "space"
            root_length = 3
        is_repository_root = len(segments) == root_length and all(segments)
        has_repository_trailing_slash = (
            len(segments) == root_length + 1 and segments[-1] == "" and all(segments[:-1])
        )
        if is_repository_root or has_repository_trailing_slash:
            return "huggingface", resource_type, None, "/" + "/".join(segments[:root_length])
        return "huggingface", resource_type, None, path

    if host == "news.ycombinator.com":
        resource_type = "item" if path.rstrip("/") == "/item" else "page"
        return "hackernews", resource_type, None, path

    return None, None, None, path


def canonicalize_url(raw_url: str) -> CanonicalURL:
    """Normalize safe identity details without discarding meaningful path or query data."""
    if not raw_url or raw_url != raw_url.strip():
        raise ValueError("URL must be non-empty and must not have surrounding whitespace")
    if any(ord(character) < 32 or character == "\\" for character in raw_url):
        raise ValueError("URL contains a control character or backslash")
    if _INVALID_PERCENT_ESCAPE.search(raw_url):
        raise ValueError("URL contains an invalid percent escape")
    try:
        parts = urlsplit(raw_url)
        hostname = parts.hostname
    except ValueError as error:
        raise ValueError(f"Malformed URL: {error}") from error

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are supported")
    if not parts.netloc or hostname is None:
        raise ValueError("URL must include a hostname")
    if any(character.isspace() for character in hostname):
        raise ValueError("URL hostname must not contain whitespace")

    origin = urlunsplit(SplitResult(scheme, parts.netloc, "/", "", ""))
    try:
        normalized_origin = url_normalize(
            origin, default_scheme=scheme, filter_params=False
        )
        if normalized_origin is None:
            raise ValueError("URL has no normalized origin")
        normalized_parts = urlsplit(normalized_origin)
        host = normalized_parts.hostname
        port = normalized_parts.port
    except (TypeError, ValueError) as error:
        raise ValueError(f"Malformed URL authority: {error}") from error
    if host is None:
        raise ValueError("URL must include a valid hostname")

    provider_host = {
        "www.github.com": "github.com",
        "www.huggingface.co": "huggingface.co",
        "www.news.ycombinator.com": "news.ycombinator.com",
    }.get(host, host)

    user_info = (
        normalized_parts.netloc.rsplit("@", 1)[0] + "@"
        if "@" in normalized_parts.netloc
        else ""
    )
    host_for_authority = f"[{provider_host}]" if ":" in provider_host else provider_host
    authority = f"{user_info}{host_for_authority}"
    if port is not None and not (scheme == "http" and port == 80) and not (
        scheme == "https" and port == 443
    ):
        authority += f":{port}"

    # Let the library normalize the origin, while retaining the original path and query semantics.
    path = parts.path or "/"
    provider, resource_type, provider_repo, path = _provider_identity(provider_host, path)
    query = _without_tracking_parameters(parts.query)
    canonical = urlunsplit(SplitResult(scheme, authority, path, query, ""))
    return CanonicalURL(
        canonical_url=canonical,
        host=provider_host,
        domain=provider_host,
        provider=provider,
        resource_type=resource_type,
        provider_repo=provider_repo,
    )
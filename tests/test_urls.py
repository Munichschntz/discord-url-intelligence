import pytest

from discord_intel.urls import canonicalize_url, extract_urls


@pytest.mark.parametrize(
    ("raw_url", "expected", "provider", "resource_type", "provider_repo"),
    [
        ("HTTP://EXAMPLE.COM", "http://example.com/", None, None, None),
        ("http://example.com:80/path", "http://example.com/path", None, None, None),
        ("https://example.com:443/path", "https://example.com/path", None, None, None),
        ("https://example.com:8443/path", "https://example.com:8443/path", None, None, None),
        ("https://example.com", "https://example.com/", None, None, None),
        ("https://example.com/path#section", "https://example.com/path", None, None, None),
        ("https://example.com/p?b=2&a=1", "https://example.com/p?b=2&a=1", None, None, None),
        (
            "https://example.com/p?x=a%2Fb&utm_source=mail&fbclid=z&keep=",
            "https://example.com/p?x=a%2Fb&keep=",
            None,
            None,
            None,
        ),
        ("https://example.com/p?%75tm_source=mail", "https://example.com/p", None, None, None),
        ("https://example.com/p?id=42", "https://example.com/p?id=42", None, None, None),
        ("https://example.com/MiXeD", "https://example.com/MiXeD", None, None, None),
        ("https://münich.example", "https://xn--mnich-kva.example/", None, None, None),
        ("http://[2001:db8::1]/", "http://[2001:db8::1]/", None, None, None),
        ("http://[2001:db8::1]:80", "http://[2001:db8::1]/", None, None, None),
        (
            "https://www.github.com/owner/repo",
            "https://github.com/owner/repo",
            "github",
            "repository",
            "owner/repo",
        ),
        (
            "https://github.com/owner/repo/",
            "https://github.com/owner/repo",
            "github",
            "repository",
            "owner/repo",
        ),
        (
            "https://github.com/OWNER/Repo",
            "https://github.com/owner/repo",
            "github",
            "repository",
            "owner/repo",
        ),
        (
            "https://github.com/owner/repo/issues/12",
            "https://github.com/owner/repo/issues/12",
            "github",
            "repository_page",
            "owner/repo",
        ),
        (
            "https://github.com/owner/repo/issues/12/",
            "https://github.com/owner/repo/issues/12/",
            "github",
            "repository_page",
            "owner/repo",
        ),
        (
            "https://github.com/owner",
            "https://github.com/owner",
            "github",
            "profile_or_page",
            None,
        ),
        (
            "https://huggingface.co/org/model/",
            "https://huggingface.co/org/model",
            "huggingface",
            "model",
            None,
        ),
        (
            "https://huggingface.co/org/model/tree/main",
            "https://huggingface.co/org/model/tree/main",
            "huggingface",
            "model",
            None,
        ),
        (
            "https://huggingface.co/datasets/org/data/",
            "https://huggingface.co/datasets/org/data",
            "huggingface",
            "dataset",
            None,
        ),
        (
            "https://huggingface.co/datasets/org/data/viewer/default/train",
            "https://huggingface.co/datasets/org/data/viewer/default/train",
            "huggingface",
            "dataset",
            None,
        ),
        (
            "https://huggingface.co/spaces/org/demo/",
            "https://huggingface.co/spaces/org/demo",
            "huggingface",
            "space",
            None,
        ),
        (
            "https://www.huggingface.co/org/model",
            "https://huggingface.co/org/model",
            "huggingface",
            "model",
            None,
        ),
        (
            "https://news.ycombinator.com/item?id=12345#comment",
            "https://news.ycombinator.com/item?id=12345",
            "hackernews",
            "item",
            None,
        ),
        (
            "https://www.news.ycombinator.com/item?id=12345&ref=home",
            "https://news.ycombinator.com/item?id=12345&ref=home",
            "hackernews",
            "item",
            None,
        ),
        (
            "https://example.net/a?token=a%2fb",
            "https://example.net/a?token=a%2fb",
            None,
            None,
            None,
        ),
        ("https://example.net/a?utm_campaign=x", "https://example.net/a", None, None, None),
        ("https://example.net/a?&x=", "https://example.net/a?&x=", None, None, None),
        (
            "https://user:pass@EXAMPLE.COM:443/path",
            "https://user:pass@example.com/path",
            None,
            None,
            None,
        ),
        (
            "https://news.ycombinator.com/item?id=12345&utm_medium=discord",
            "https://news.ycombinator.com/item?id=12345",
            "hackernews",
            "item",
            None,
        ),
    ],
)
def test_canonicalization_cases(
    raw_url: str,
    expected: str,
    provider: str | None,
    resource_type: str | None,
    provider_repo: str | None,
) -> None:
    result = canonicalize_url(raw_url)
    assert result.canonical_url == expected
    assert result.provider == provider
    assert result.resource_type == resource_type
    assert result.provider_repo == provider_repo


@pytest.mark.parametrize(
    "raw_url",
    [
        "",
        "ftp://example.com/file",
        "https:///missing-host",
        "https://example.com:99999/",
        "https://[not-ipv6]/",
        "https://exa mple.com/",
        " https://example.com/",
        "https://example.com/path\\name",
    ],
)
def test_invalid_urls_are_rejected(raw_url: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_url(raw_url)


@pytest.mark.parametrize(
    ("content", "expected_urls"),
    [
        ("See https://example.com", ["https://example.com"]),
        ("(https://example.com/path).", ["https://example.com/path"]),
        ("<https://example.com/path>", ["https://example.com/path"]),
        ("https://example.com/a_(b)", ["https://example.com/a_(b)"]),
        ("https://example.com/a_(b)).", ["https://example.com/a_(b)"]),
        ("one https://a.example two https://b.example!", ["https://a.example", "https://b.example"]),
        ("repeat https://a.example https://a.example", ["https://a.example", "https://a.example"]),
        ("ftp://example.com and javascript:alert(1)", []),
        ("?https://example.com/path,", ["https://example.com/path"]),
        ("é https://example.com/path", ["https://example.com/path"]),
    ],
)
def test_extraction_preserves_raw_url_and_exact_offsets(
    content: str, expected_urls: list[str]
) -> None:
    occurrences = extract_urls(content)
    assert [occurrence.raw_url for occurrence in occurrences] == expected_urls
    for occurrence in occurrences:
        assert content[occurrence.start_offset : occurrence.end_offset] == occurrence.raw_url
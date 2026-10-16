"""HTML fetching and linked-reference rendering for the showcase.

Pipeline, end to end:
1. ``fetch_formatted_page`` downloads a decision/agenda page and returns both the
   cleaned HTML (scripts/noscript stripped) and a plain-text rendering used upstream
   for mention extraction (see ``extraction.py``).
2. Extraction (elsewhere) turns that text into ``DocumentReference`` objects, each
   carrying one or more ``Mention`` strings -- the literal substrings in the page
   text that referred to a legal document.
3. ``write_linked_html`` walks the resolved/unresolved outcomes and, for each
   reference, tries its mentions in order against the original HTML via
   ``mark_mention_in_soup``, wrapping each one found in an ``<a>`` tag. By default
   every mention is linked (``link_all_occurrences=True``); pass ``False`` to stop
   after the first successful match instead.
4. ``mark_mention_in_soup`` does the actual text-to-DOM matching (see its own
   docstring for the two-pass strategy).
5. ``read_linked_html`` is the inverse of step 3: it parses a previously-written
   linked HTML file back into ``(DocumentReference, ResolutionResponse)`` pairs,
   used to reuse cached resolutions instead of re-resolving.
"""

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from src.agent_helpers.models import ResolutionResponse, ResolutionStatus
from src.document_helpers.aggregation import ReferenceOutcome
from src.document_helpers.extraction import DocumentReference, Mention
from src.models import SearchResult

logger = logging.getLogger(__name__)

REFERENCE_STYLE = """
<style>
a.legal-reference { border-radius: 0.15em; color: inherit; padding: 0 0.15em; text-decoration: underline; text-decoration-style: dotted; }
a.legal-reference.resolved { background-color: #c8f7c5; }
a.legal-reference.qualified { background-color: #bcdffb; }
a.legal-reference.unresolved { background-color: #fff3a3; }
aside.legal-reference-marking-warning { background-color: #ffd6d6; border: 1px solid #b42318; color: #7a1a13; margin: 0 0 1em; padding: 0.75em 1em; }
</style>
"""

# ebesluitvorming.gent.be's WAF returns 403 for bot-like User-Agents.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
}


def fetch_formatted_page(url: str) -> tuple[str, str]:
    """Fetch `url` and return (cleaned HTML, plain text) for extraction + rendering."""
    response = None
    for attempt in range(3):
        response = requests.get(url, timeout=30, headers=BROWSER_HEADERS)
        if response.status_code not in {403, 429, 500, 502, 503, 504}:
            break
        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))
    assert response is not None
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup.select("script, noscript"):
        tag.decompose()
    html = str(soup)
    text_soup = BeautifulSoup(html, "html.parser")
    for tag in text_soup.select("style, nav, footer, svg"):
        tag.decompose()
    for item in text_soup.select("li"):
        item.insert(0, "• ")
    lines = [line.strip() for line in text_soup.get_text("\n").splitlines()]
    return html, "\n".join(line for line in lines if line)


def mark_mention_in_soup(content, mention: str, attrs: dict, soup: BeautifulSoup) -> bool:
    """Find `mention`'s text inside `content` and wrap the first match in an `<a>` tag.

    The mention string comes from plain-text extraction, so it may not align with a
    single DOM text node (HTML can split a sentence across inline tags, or collapse
    whitespace differently). Matching therefore runs in two passes, returning as
    soon as either one succeeds:

    1. Single-node pass: build a regex from the mention (literal chars, with any
       whitespace run treated as flexible `\s+`) and search each individual text
       node. This is the common case where the mention sits entirely within one
       node.
    2. Cross-node fallback: for mentions split across sibling inline nodes (e.g.
       "<b>Art.</b> 5"), walk block-level containers (p/li/h*/td/th/div, excluding
       ones that nest another block container) and concatenate their text nodes
       into one string to search against. If the match spans multiple text nodes,
       the tag is inserted before the first node, the first/last nodes are
       trimmed to the non-matching remainder, and any fully-covered middle nodes
       are removed.
    """
    if not mention or not mention.strip():
        return False
    # Whitespace in the mention is normalized to \s+ so differences in HTML
    # formatting (line breaks, multiple spaces) don't prevent a match.
    pattern = "".join(r"\s+" if part.isspace() else re.escape(part) for part in re.split(r"(\s+)", mention.strip()))
    matcher = re.compile(pattern, re.IGNORECASE)

    # Pass 1: mention fully contained in a single text node.
    for node in list(content.find_all(string=True)):
        if node.parent and node.parent.name in {"a", "script", "style"}:
            continue
        source = str(node)
        match = matcher.search(source)
        if match:
            tag = soup.new_tag("a", attrs=attrs.copy())
            tag.string = source[match.start():match.end()]
            node.replace_with(source[:match.start()], tag, source[match.end():])
            return True

    # Pass 2: mention split across sibling nodes within one block container.
    for container in content.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "div"]):
        if container.find(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th"]):
            continue  # skip outer containers; only match the innermost block
        nodes = []
        full_text = ""
        for node in container.find_all(string=True):
            if node.parent and node.parent.name in {"a", "script", "style"}:
                continue
            start = len(full_text)
            full_text += str(node)
            nodes.append((node, start, len(full_text)))
        match = matcher.search(full_text)
        if not nodes or not match:
            continue
        # Nodes whose text range overlaps the match span are the ones to rewrite.
        overlap = [node for node in nodes if node[2] > match.start() and node[1] < match.end()]
        if not overlap:
            continue
        tag = soup.new_tag("a", attrs=attrs.copy())
        tag.string = full_text[match.start():match.end()]
        if len(overlap) == 1:
            node, start, _ = overlap[0]
            node.replace_with(str(node)[:match.start() - start], tag, str(node)[match.end() - start:])
            return True
        # Match spans multiple nodes: insert the tag once, trim the edge nodes to
        # their non-matching remainder, and drop any fully-matched middle nodes.
        first, first_start, _ = overlap[0]
        last, last_start, _ = overlap[-1]
        first_parent = first.parent
        first_parent.insert_after(tag)
        first.replace_with(str(first)[:match.start() - first_start])
        last.replace_with(str(last)[match.end() - last_start:])
        for middle, _, _ in overlap[1:-1]:
            middle.extract()
        return True
    return False


def _outcome_parts(item: ReferenceOutcome | dict):
    if isinstance(item, ReferenceOutcome):
        return item.extracted, item.resolution
    return item["reference"], item.get("results")


def write_linked_html(
    html: str,
    outcomes: list[ReferenceOutcome | dict],
    output_file: str | Path,
    link_all_occurrences: bool = True,
) -> None:
    """Re-render `html` with each reference's matched mentions turned into links.

    For every outcome, builds the `<a>` attributes (resolution metadata plus, when
    resolved, `href`) once, then tries the reference's mentions in order via
    `mark_mention_in_soup`. Each mention occurrence that extraction recorded gets its
    own entry in `reference.mentions`, so matching them all links every occurrence in
    the page. When `link_all_occurrences` is False, matching stops after the first
    mention is found, linking only one occurrence per reference.
    """
    soup = BeautifulSoup(html, "html.parser")
    content = soup.body or soup
    marking_failures: list[tuple[str, str]] = []
    for item in outcomes:
        reference, response = _outcome_parts(item)
        is_linkable = response and response.status in {
            ResolutionStatus.RESOLVED,
            ResolutionStatus.RESOLVED_WITH_CAVEAT,
        } and response.results
        result_url = response.results[0].url if is_linkable else None
        link_class = (
            "resolved"
            if response and response.status == ResolutionStatus.RESOLVED
            else "qualified"
            if result_url
            else "unresolved"
        )
        attrs = {
            "class": f"legal-reference {link_class}",
            "data-doc-reference": reference.doc_reference,
            "data-reference-class": reference.reference_class,
            "data-context": reference.context,
            "data-resolution-status": response.status.value if response else "unresolved",
            "data-reason-code": response.reason_code.value if response else "source_no_match",
        }
        if response and response.caveat:
            attrs["title"] = response.caveat
        if result_url:
            attrs.update({"href": result_url, "target": "_blank", "rel": "noopener noreferrer"})
        for mention in reference.mentions:
            mention_text = mention.text if isinstance(mention, Mention) else mention
            if mark_mention_in_soup(content, mention_text, attrs, soup):
                if not link_all_occurrences:
                    break
            else:
                marking_failures.append((reference.doc_reference, mention_text))
    if marking_failures:
        logger.warning(
            "Failed to mark %d reference mention(s) in linked HTML: %s",
            len(marking_failures),
            "; ".join(f"{reference}: {mention!r}" for reference, mention in marking_failures),
        )
        warning = soup.new_tag(
            "aside",
            attrs={
                "class": "legal-reference-marking-warning",
                "data-marking-failures": str(len(marking_failures)),
            },
        )
        title = soup.new_tag("strong")
        title.string = "References not marked in this HTML"
        warning.append(title)
        failure_list = soup.new_tag("ul")
        for reference, mention in marking_failures:
            item = soup.new_tag("li")
            item.string = f"{reference}: {mention}"
            failure_list.append(item)
        warning.append(failure_list)
        content.insert(0, warning)
    if soup.head:
        soup.head.append(BeautifulSoup(REFERENCE_STYLE, "html.parser"))
    else:
        soup.insert(0, BeautifulSoup(REFERENCE_STYLE, "html.parser"))
    Path(output_file).write_text(str(soup), encoding="utf-8")


def read_linked_html(input_file: str | Path) -> tuple[str, list[dict]]:
    """Inverse of `write_linked_html`: reconstruct references/resolutions from the
    `data-*` attributes and href previously written onto `a.legal-reference` tags,
    so a cached linked page can be reused without re-resolving.
    """
    html = Path(input_file).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    processed: list[dict] = []
    for link in (soup.body or soup).select("a.legal-reference"):
        doc_reference = link.get("data-doc-reference") or link.get_text(strip=True)
        mention = str(link.string or "").strip()
        reference = DocumentReference(
            doc_reference=doc_reference,
            reference_class=link.get("data-reference-class", ""),
            context=link.get("data-context", ""),
            mentions=[Mention(text=mention, start=0, end=len(mention))],
        )
        result_url = link.get("href")
        response = ResolutionResponse(
            reference=doc_reference,
            status=link.get("data-resolution-status", "unresolved"),
            reason_code=link.get("data-reason-code", "confirmed" if link.get("data-resolution-status") == "resolved" else "source_no_match"),
            results=[SearchResult(title=doc_reference, url=result_url, source="linked_html", doc_id=result_url or doc_reference, retrieved_at=datetime.now(timezone.utc), metadata={"cached_from": "linked_html"})] if result_url else [],
            reason="Cached from linked HTML",
            attempt_count=1,
            trace=[],
            caveat=link.get("title"),
        )
        processed.append({"reference": reference, "results": response})
    return html, processed

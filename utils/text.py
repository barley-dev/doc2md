"""Text processing utilities for doc2md."""

import re
import sys
import unicodedata
from collections import Counter


# ─── Language detection signatures (simplified for v0.5.0) ───────────────────

_GERMAN_SIGNATURE_WORDS = {
    'und', 'die', 'der', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einer',
    'mit', 'von', 'für', 'fur', 'auf', 'aus', 'bei', 'nach', 'über', 'uber',
    'als', 'auch', 'oder', 'aber', 'wenn', 'wird', 'sind', 'hat', 'ist',
    'nicht', 'kann', 'durch', 'werden', 'wurde', 'diese', 'dieser',
    'zwischen', 'unter', 'ohne', 'gegen', 'noch', 'sehr', 'schon',
}

_FRENCH_SIGNATURE_WORDS = {
    'les', 'des', 'une', 'dans', 'pour', 'avec', 'sur', 'par', 'qui', 'que',
    'est', 'sont', 'pas', 'plus', 'nous', 'vous', 'mais', 'cette', 'entre',
    'comme', 'leur', 'aussi', 'peut', 'tous', 'même', 'meme',
}


def filter_noise(text, compiled_patterns, safety_threshold=150):
    """Generic noise filter: remove lines matching any of the compiled_patterns.

    Lines longer than safety_threshold are always kept (safety valve against
    false positives on long reference strings).

    Args:
        text: Input Markdown text.
        compiled_patterns: List of compiled re.Pattern objects.
        safety_threshold: Lines longer than this are never removed.

    Returns:
        Filtered text with noise lines removed.
    """
    if not compiled_patterns:
        return text

    lines = text.split('\n')
    kept = []
    removed_count = 0

    for line in lines:
        stripped = line.strip()

        # Keep empty lines
        if not stripped:
            kept.append(line)
            continue

        # Safety valve: skip long lines
        if len(stripped) > safety_threshold:
            kept.append(line)
            continue

        matched = any(pattern.search(stripped) for pattern in compiled_patterns)

        if matched:
            removed_count += 1
        else:
            kept.append(line)

    if removed_count > 0:
        print(f"  Layer 1: removed {removed_count} noise lines", file=sys.stderr)

    return '\n'.join(kept)


def filter_journal_noise(text):
    """Legacy wrapper: load journal profile and filter noise.
    v0.10.0: patterns come from profiles/journal.yaml (canonical source).

    Note: if journal.yaml is missing or corrupted, this will print an error
    and exit. This is intentional — a missing canonical source is a fatal
    configuration error, not a recoverable runtime condition."""
    from profiles import load_profile
    profile = load_profile('journal')
    patterns = profile['noise']['compiled_patterns']
    threshold = profile['noise']['safety_threshold']
    return filter_noise(text, patterns, threshold)


def detect_language(doc, sample_pages=2):
    """Detect document language based on word frequency analysis.
    Returns 'de', 'fr', or 'en' (default).
    Simplified for v0.5.0: only used for tagging, not encoding fix."""
    word_counter = Counter()
    pages_to_check = min(sample_pages, len(doc))

    for i in range(pages_to_check):
        text = doc[i].get_text()
        words = re.findall(r'\b[a-zA-ZäöüÄÖÜßàâçéèêëîïôùûüÿœæ]+\b', text.lower())
        word_counter.update(words)

    # Count signature word hits
    de_hits = sum(word_counter[w] for w in _GERMAN_SIGNATURE_WORDS if w in word_counter)
    fr_hits = sum(word_counter[w] for w in _FRENCH_SIGNATURE_WORDS if w in word_counter)

    threshold = 5
    if de_hits >= threshold and de_hits > fr_hits:
        return 'de'
    elif fr_hits >= threshold and fr_hits > de_hits:
        return 'fr'
    return 'en'


def post_process(text):
    """Clean up the final Markdown text."""
    # Replace garbled decoration lines (CID font decode failures -> U+FFFD sequences)
    # with a Markdown HR. These originate from PDF rule/separator lines using
    # unknown CID fonts, and --- is the semantic Markdown equivalent.
    FFFD = '\ufffd'
    lines_in = text.split('\n')
    lines_out = []
    for line in lines_in:
        stripped = line.strip()
        if stripped:
            fffd_count = stripped.count(FFFD)
            if fffd_count >= 5 and fffd_count / len(stripped) >= 0.2:
                lines_out.append('---')
                continue
        lines_out.append(line)
    text = '\n'.join(lines_out)

    # Normalize Unicode
    text = unicodedata.normalize('NFC', text)

    # Remove empty markdown tables (image placeholder remnants).
    # Matches single-column tables where every data cell is blank:
    #   |  |
    #   | --- |
    #   |  |
    # Allow any number of blank rows before/after the separator.
    text = re.sub(
        r'(?:^\|[ \t]*\|\n)+\| ?-{3,} ?\|\n(?:^\|[ \t]*\|\n)+',
        '',
        text,
        flags=re.MULTILINE,
    )
    # Also catch a minimal 2-row empty table: header + separator only (no data rows)
    text = re.sub(
        r'^\|[ \t]*\|\n\| ?-{3,} ?\|\n',
        '',
        text,
        flags=re.MULTILINE,
    )

    # Remove excessive blank lines (3+ -> 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Remove trailing whitespace on lines
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # Ensure final newline
    if not text.endswith('\n'):
        text += '\n'

    return text

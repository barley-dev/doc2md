"""Image-related utilities for doc2md."""

import re

# EMU to pixel conversion (1 inch = 914400 EMU, 96 DPI)
EMU_PER_PIXEL = 914400 / 96


def _check_content_sufficient(md_text, threshold=100):
    """Check if extracted markdown content has enough meaningful text.
    Returns True if content is sufficient, False if fallback is needed."""
    # Strip frontmatter
    text = re.sub(r'^---\n.*?\n---\n', '', md_text, flags=re.DOTALL)
    # Strip markdown syntax characters and whitespace
    text = re.sub(r'[#\-|*>\s`\[\]()!_=~^\\]', '', text)
    return len(text) >= threshold

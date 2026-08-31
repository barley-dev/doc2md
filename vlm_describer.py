"""VLM (Vision Language Model) image description module for doc2md.

Supports two backends:
  - Gemini (default): pip install google-genai, GOOGLE_API_KEY
  - Claude: pip install anthropic, ANTHROPIC_API_KEY

API keys are read from the environment. A .env file is also supported:
set DOC2MD_ENV_FILE, or place .env in the current directory or ~/.doc2md.env.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

# Optional .env support. Checked in order; the first existing file wins.
# Override the location with the DOC2MD_ENV_FILE environment variable.
try:
    from dotenv import load_dotenv

    _candidates = []
    if os.environ.get("DOC2MD_ENV_FILE"):
        _candidates.append(Path(os.environ["DOC2MD_ENV_FILE"]).expanduser())
    _candidates += [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path.home() / ".doc2md.env",
    ]
    for _env_path in _candidates:
        if _env_path.is_file():
            load_dotenv(_env_path)
            break
except ImportError:
    pass


# ─── Single source of truth for default VLM model ────────────────────────────
DEFAULT_VLM_MODEL = "gemini-3-flash-preview"

# Chemistry-specific VLM prompt template
_VLM_PROMPT = """Analyze this page from a chemistry research paper. For each figure, scheme, or table visible:

1. Identify the type: Scheme / Figure / Table
2. Identify the label (e.g., "Scheme 1", "Figure 2", "Table 1")
3. Provide a concise but informative description:
   - For Schemes: describe the reaction (substrates → products, catalyst, conditions)
   - For Figures: describe what is shown (spectra, crystal structure, kinetics plot, etc.)
   - For Tables: summarize the data (what is being compared, key trends)
4. For chemical structures: give common names or IUPAC names when recognizable

Output format — one block per item, using this exact template:
<!-- VLM: [Label] — [Description] -->

If the page contains only text with no figures/schemes/tables, output:
<!-- VLM: (text only) -->

Be concise. Focus on chemical content. Do not describe page layout or formatting."""


def parse_page_range(spec: str | None, total: int) -> set[int]:
    """Parse page range spec like '1-5,10,15-20' to 0-indexed page set.

    Args:
        spec: Page range string (1-indexed, human-readable). None = all pages.
        total: Total number of pages in document.

    Returns:
        Set of 0-indexed page numbers.

    Raises:
        ValueError: If spec contains non-numeric, non-delimiter characters.
    """
    if spec is None:
        return set(range(total))

    spec = spec.strip()
    if not spec:
        return set()

    pages = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part and not part.startswith('-'):
            start_s, end_s = part.split('-', 1)
            start = max(1, int(start_s.strip()))
            end = min(total, int(end_s.strip()))
            pages.update(range(start - 1, end))
        else:
            p = int(part)
            if 1 <= p <= total:
                pages.add(p - 1)
    return pages


def _is_gemini_model(model: str) -> bool:
    """Check if model name refers to a Gemini model."""
    return model.startswith("gemini-")


def _describe_page_gemini(page_png_bytes: bytes, model: str,
                          prompt: str, max_tokens: int) -> str:
    """Describe a page using Gemini Vision API."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("  Warning: google-genai package not installed, skipping VLM", file=sys.stderr)
        return ""

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("  Warning: GOOGLE_API_KEY not set, skipping VLM", file=sys.stderr)
        return ""

    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=page_png_bytes, mime_type="image/png"),
                prompt,
            ],
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        return response.text.strip()
    except Exception as e:
        print(f"  Warning: Gemini VLM API call failed: {e}", file=sys.stderr)

    return ""


def _describe_page_claude(page_png_bytes: bytes, model: str,
                          prompt: str, max_tokens: int) -> str:
    """Describe a page using Claude Vision API."""
    try:
        import anthropic
    except ImportError:
        print("  Warning: anthropic package not installed, skipping VLM", file=sys.stderr)
        return ""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  Warning: ANTHROPIC_API_KEY not set, skipping VLM", file=sys.stderr)
        return ""

    client = anthropic.Anthropic(api_key=api_key)
    image_data = base64.standard_b64encode(page_png_bytes).decode("utf-8")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
    except Exception as e:
        print(f"  Warning: Claude VLM API call failed: {e}", file=sys.stderr)

    return ""


def describe_page(page_png_bytes: bytes, model: str = None,
                  prompt: str = None, max_tokens: int = None) -> str:
    """Send a rendered page image to a VLM and get descriptions.

    Dispatches to Gemini or Claude based on model name prefix.

    Args:
        page_png_bytes: PNG image bytes of the rendered page.
        model: Model name (default: gemini-2.0-flash). Gemini models start with 'gemini-'.
        prompt: VLM prompt text. Falls back to module-level _VLM_PROMPT if not provided.
        max_tokens: Max tokens for the response. Falls back to 1024 if not provided.

    Returns:
        VLM description string (HTML comment blocks).
    """
    effective_model = model if model is not None else DEFAULT_VLM_MODEL
    effective_prompt = prompt if prompt is not None else _VLM_PROMPT
    effective_max_tokens = max_tokens if max_tokens is not None else 1024

    if _is_gemini_model(effective_model):
        return _describe_page_gemini(page_png_bytes, effective_model, effective_prompt, effective_max_tokens)
    else:
        return _describe_page_claude(page_png_bytes, effective_model, effective_prompt, effective_max_tokens)


def describe_all_pages(doc, dpi: int = 150, model: str = None,
                       prompt: str = None, max_tokens: int = None,
                       pages: str = None) -> dict[int, str]:
    """Describe pages in a PyMuPDF document using VLM.

    Args:
        doc: PyMuPDF Document object.
        dpi: Resolution for page rendering.
        model: Claude model to use.
        prompt: VLM prompt text. Falls back to module-level _VLM_PROMPT if not provided.
        max_tokens: Max tokens for the response. Falls back to 1024 if not provided.
        pages: Page range spec (e.g. '1-5,10'). None = all pages.

    Returns:
        Dict mapping page_num (0-indexed) → VLM description string.
    """
    page_set = parse_page_range(pages, len(doc))
    descriptions = {}
    total = len(doc)

    for page_num in range(total):
        if page_num not in page_set:
            continue
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")

        print(f"  VLM: describing page {page_num + 1}/{total}...", file=sys.stderr)
        desc = describe_page(png_bytes, model=model, prompt=prompt, max_tokens=max_tokens)

        if desc and "(text only)" not in desc:
            descriptions[page_num] = desc

    return descriptions

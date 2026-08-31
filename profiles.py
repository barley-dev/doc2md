"""Profile loader for doc2md.

Loads YAML profiles from the profiles/ directory, compiles regex patterns,
and resolves prompt file paths relative to doc2md.py location.
"""

import re
import sys
from pathlib import Path


# Base directory: same directory as doc2md.py (this file's location)
_BASE_DIR = Path(__file__).parent
_PROFILES_DIR = _BASE_DIR / "profiles"


def _compile_flags(flags_str):
    """Convert a flags string like 'IGNORECASE' to re flags int."""
    if not flags_str:
        return 0
    flag = 0
    for part in str(flags_str).split('|'):
        part = part.strip().upper()
        if part == 'IGNORECASE':
            flag |= re.IGNORECASE
        elif part == 'MULTILINE':
            flag |= re.MULTILINE
        elif part == 'DOTALL':
            flag |= re.DOTALL
        elif part == 'VERBOSE':
            flag |= re.VERBOSE
    return flag


def load_profile(name: str) -> dict:
    """Load a named profile from the profiles/ directory.

    Args:
        name: Profile name (e.g. 'journal', 'textbook', 'default').
              Can also be a full path to a .yaml file.

    Returns:
        dict with keys: name, vlm, noise
    """
    try:
        import yaml
    except ImportError:
        print("Error: PyYAML is required for profiles. Install with: pip install PyYAML",
              file=sys.stderr)
        sys.exit(1)

    # Resolve profile path
    profile_path = Path(name)
    if not profile_path.suffix:
        profile_path = _PROFILES_DIR / f"{name}.yaml"
    elif not profile_path.is_absolute():
        profile_path = _PROFILES_DIR / profile_path

    if not profile_path.exists():
        available = list_profiles()
        print(f"Error: Profile '{name}' not found at {profile_path}", file=sys.stderr)
        print(f"  Available profiles: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    with open(profile_path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        print(f"Error: Profile '{name}' is not a valid YAML mapping", file=sys.stderr)
        sys.exit(1)

    # ── VLM section ──────────────────────────────────────────────────────────
    vlm_raw = raw.get('vlm', {}) or {}
    prompt_file = vlm_raw.get('prompt_file', 'prompts/default.txt')
    prompt_path = _BASE_DIR / prompt_file

    if prompt_path.exists():
        with open(prompt_path, 'r', encoding='utf-8') as f:
            prompt_text = f.read().strip()
    else:
        print(f"  Warning: VLM prompt file not found: {prompt_path}, using empty prompt",
              file=sys.stderr)
        prompt_text = ""

    vlm = {
        "prompt": prompt_text,
        "max_tokens": vlm_raw.get('max_tokens', 1024),
    }
    if 'model' in vlm_raw:
        vlm["model"] = vlm_raw["model"]

    # ── Noise section ─────────────────────────────────────────────────────────
    noise_raw = raw.get('noise', {}) or {}
    rules = noise_raw.get('rules', []) or []
    compiled_patterns = []
    for rule in rules:
        if isinstance(rule, dict):
            pattern_str = rule.get('pattern', '')
            flags_str = rule.get('flags', '')
        else:
            pattern_str = str(rule)
            flags_str = ''
        if not pattern_str:
            continue
        try:
            flags = _compile_flags(flags_str)
            compiled_patterns.append(re.compile(pattern_str, flags))
        except re.error as e:
            print(f"  Warning: Invalid noise pattern '{pattern_str}': {e}", file=sys.stderr)

    noise = {
        "compiled_patterns": compiled_patterns,
        "safety_threshold": noise_raw.get('safety_threshold', 150),
    }

    return {
        "name": raw.get('name', name),
        "vlm": vlm,
        "noise": noise,
    }


def list_profiles() -> list:
    """Return sorted list of available profile names (without .yaml extension)."""
    if not _PROFILES_DIR.exists():
        return []
    return sorted(p.stem for p in _PROFILES_DIR.glob("*.yaml"))

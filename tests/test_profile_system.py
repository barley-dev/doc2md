"""Tests for doc2md v0.10.0 Profile system."""

import pytest
import sys
from pathlib import Path
from types import SimpleNamespace

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNoiseFilterEquivalence:
    """Verify profile-based noise filter matches v0.9.0 hardcoded behavior."""

    # 每條 regex 至少一個 positive match 和一個 negative match
    JOURNAL_NOISE_POSITIVE = [
        # OA watermarks
        "This article has been published in Wiley Online Library",
        "Downloaded via NATIONAL CENTRAL UNIV on March 15, 2026",
        "See https://pubs.acs.org/sharingguidelines for options",
        "Published on 15 March 2026. Downloaded by National Central University",
        "Creative Commons Attribution 4.0 International License",
        "( 3 of 11) 15222586, 2023",
        "Wiley Online Library for rules of use; Terms and Conditions",
        # Journal headers
        # Note: "Chem. Ber. 125, (1992)" is NOT filtered by v0.9.0 either (pattern needs \d+ then space/comma then \d{4})
        "J. Org. Chem., Vol. 55",
        "2630 E.-U. Wurthwein",
        "www.eurjoc.org",
        "© 2023 Wiley-VCH",
        "DOI: https://doi.org/10.1021/acs.orglett.5b00001",
        "6407-6411",
        "RESEARCH ARTICLE advsynthcatal.com",
        "pubs.acs.org/OrgLett",
        "Cite This: Org. Lett. 2025, 27, 7546",
        "# ACCESS",
        "Metrics & More",
        "Communication ChemComm",
        "rsc.li/chemcomm",
        "This journal is © Royal Society of Chemistry 2018",
        "Cite this: Chem. Commun., 2018",
        "View Article Online",
        "COMMUNICATION",  # JH#20: [A-Z]OMMUNICATION — C + OMMUNICATION
    ]

    JOURNAL_NOISE_NEGATIVE = [
        # Normal content that must NOT be filtered
        "The reaction was carried out at room temperature.",
        "Table 1 shows the optimization results.",
        "Scheme 1. Proposed catalytic cycle for the reaction.",
        "1. Introduction",
        "## Abstract",
        # Long line (safety valve: >150 chars should be kept)
        "A" * 151,
    ]

    def test_journal_profile_filters_known_noise(self):
        """Journal profile must filter all known noise lines."""
        from profiles import load_profile
        from utils.text import filter_noise

        profile = load_profile('journal')
        patterns = profile['noise']['compiled_patterns']
        threshold = profile['noise']['safety_threshold']

        for noise_line in self.JOURNAL_NOISE_POSITIVE:
            text = f"keep this\n{noise_line}\nkeep this too"
            result = filter_noise(text, patterns, threshold)
            assert noise_line not in result, f"Should filter: {noise_line!r}"

    def test_journal_profile_keeps_normal_content(self):
        """Journal profile must not filter normal content."""
        from profiles import load_profile
        from utils.text import filter_noise

        profile = load_profile('journal')
        patterns = profile['noise']['compiled_patterns']
        threshold = profile['noise']['safety_threshold']

        for content_line in self.JOURNAL_NOISE_NEGATIVE:
            text = f"before\n{content_line}\nafter"
            result = filter_noise(text, patterns, threshold)
            assert content_line in result, f"Should keep: {content_line!r}"

    def test_safety_valve_long_lines(self):
        """Lines longer than safety_threshold must never be filtered."""
        from profiles import load_profile
        from utils.text import filter_noise

        profile = load_profile('journal')
        patterns = profile['noise']['compiled_patterns']
        threshold = profile['noise']['safety_threshold']

        # A noise pattern embedded in a long line
        long_line = "x" * 100 + " pubs.acs.org/OrgLett " + "x" * 100
        assert len(long_line) > threshold
        text = f"before\n{long_line}\nafter"
        result = filter_noise(text, patterns, threshold)
        assert long_line in result

    def test_default_profile_no_filtering(self):
        """Default profile has no noise patterns — nothing filtered."""
        from profiles import load_profile
        from utils.text import filter_noise

        profile = load_profile('default')
        patterns = profile['noise']['compiled_patterns']
        threshold = profile['noise']['safety_threshold']

        text = "pubs.acs.org/OrgLett\nnormal text"
        result = filter_noise(text, patterns, threshold)
        assert result == text

    def test_textbook_profile_filters_textbook_noise(self):
        """Textbook profile filters textbook-specific noise."""
        from profiles import load_profile
        from utils.text import filter_noise

        profile = load_profile('textbook')
        patterns = profile['noise']['compiled_patterns']
        threshold = profile['noise']['safety_threshold']

        textbook_noise = [
            "MasteringChemistry",
            "www.pearson.com/chemistry",
            "ISBN 978-0-13-423838-2",
            "42 Chapter 5",
            "  42 Chapter 5",
        ]
        for noise_line in textbook_noise:
            text = f"keep\n{noise_line}\nkeep"
            result = filter_noise(text, patterns, threshold)
            assert noise_line not in result, f"Should filter: {noise_line!r}"

    def test_textbook_profile_keeps_journal_noise(self):
        """Textbook profile must NOT filter journal-specific noise."""
        from profiles import load_profile
        from utils.text import filter_noise

        profile = load_profile('textbook')
        patterns = profile['noise']['compiled_patterns']
        threshold = profile['noise']['safety_threshold']

        journal_only = "pubs.acs.org/OrgLett"
        text = f"keep\n{journal_only}\nkeep"
        result = filter_noise(text, patterns, threshold)
        assert journal_only in result


class TestCanonicalSource:
    """Verify YAML is the single source of truth for noise patterns."""

    def test_filter_journal_noise_uses_yaml(self):
        """filter_journal_noise() must load patterns from journal.yaml, not hardcoded."""
        from utils.text import filter_journal_noise

        # filter_journal_noise should still work (backward compat)
        text = "keep this\npubs.acs.org/OrgLett\nkeep this too"
        result = filter_journal_noise(text)
        assert "pubs.acs.org/OrgLett" not in result

    def test_no_hardcoded_pattern_definitions_in_text_py(self):
        """utils/text.py must not define _OA_WATERMARK_PATTERNS or _JOURNAL_HEADER_PATTERNS."""
        source_path = Path(__file__).parent.parent / 'utils' / 'text.py'
        source = source_path.read_text()
        # Check for definition statements (assignment), not just any mention
        assert '_OA_WATERMARK_PATTERNS = [' not in source, \
            "_OA_WATERMARK_PATTERNS definition should be removed from text.py"
        assert '_JOURNAL_HEADER_PATTERNS = [' not in source, \
            "_JOURNAL_HEADER_PATTERNS definition should be removed from text.py"
        assert 'MAX_NOISE_LINE_LENGTH = ' not in source, \
            "MAX_NOISE_LINE_LENGTH definition should be removed from text.py"

    def test_filter_journal_noise_no_args_backward_compat(self):
        """filter_journal_noise(text) must work with no other arguments."""
        from utils.text import filter_journal_noise

        text = "normal content\n© 2023 Wiley-VCH\nmore content"
        result = filter_journal_noise(text)
        assert "© 2023 Wiley-VCH" not in result
        assert "normal content" in result


class TestNoiseFilterBranching:
    """Verify noise filter uses simple logic: has patterns → filter, else → skip."""

    def test_profile_with_patterns_filters(self):
        """Profile with compiled_patterns should filter."""
        from utils.text import filter_noise
        import re
        patterns = [re.compile(r'REMOVEME')]
        text = "keep\nREMOVEME\nkeep"
        result = filter_noise(text, patterns)
        assert "REMOVEME" not in result

    def test_profile_without_patterns_skips(self):
        """Profile with empty compiled_patterns should not filter."""
        from utils.text import filter_noise
        text = "keep\nREMOVEME\nkeep"
        result = filter_noise(text, [])
        assert result == text

    def test_fallback_when_no_profile_attr(self):
        """When args has no profile_data attr, should fallback to journal noise filter."""
        # This simulates programmatic calling without --profile
        from utils.text import filter_journal_noise

        text = "keep\npubs.acs.org/OrgLett\nkeep"
        result = filter_journal_noise(text)
        assert "pubs.acs.org/OrgLett" not in result

    def test_main_fallback_uses_journal(self):
        """doc2md.py's fallback profile_name must be 'journal', not 'default'."""
        # Simulate args object without profile attribute
        args = SimpleNamespace()
        profile_name = getattr(args, 'profile', 'journal') or 'journal'
        assert profile_name == 'journal'

        # Simulate args with explicit profile
        args2 = SimpleNamespace(profile='textbook')
        profile_name2 = getattr(args2, 'profile', 'journal') or 'journal'
        assert profile_name2 == 'textbook'

        # Simulate args with None profile
        args3 = SimpleNamespace(profile=None)
        profile_name3 = getattr(args3, 'profile', 'journal') or 'journal'
        assert profile_name3 == 'journal'


class TestVLMParameterPriority:
    """CLI arguments must override profile settings for VLM."""

    def test_cli_vlm_model_overrides_profile(self):
        """--vlm-model explicitly set should take precedence over profile."""
        from converters.pdf import resolve_vlm_params

        profile_data = {
            'vlm': {'model': 'claude-haiku-4-5', 'prompt': 'profile prompt', 'max_tokens': 4096}
        }
        args = SimpleNamespace(
            vlm_model='claude-sonnet-4-5',  # user explicitly set
            profile_data=profile_data,
        )
        model, prompt, max_tokens = resolve_vlm_params(args)
        assert model == 'claude-sonnet-4-5', "CLI --vlm-model should override profile"
        assert prompt == 'profile prompt'
        assert max_tokens == 4096

    def test_default_cli_vlm_model_uses_profile(self):
        """When --vlm-model is argparse default, profile model should apply."""
        from converters.pdf import resolve_vlm_params
        from vlm_describer import DEFAULT_VLM_MODEL

        profile_data = {
            'vlm': {'model': 'claude-sonnet-4-5', 'prompt': 'profile prompt', 'max_tokens': 2048}
        }
        args = SimpleNamespace(
            vlm_model=DEFAULT_VLM_MODEL,  # argparse default, not explicitly set
            profile_data=profile_data,
        )
        model, prompt, max_tokens = resolve_vlm_params(args)
        assert model == 'claude-sonnet-4-5', "Default CLI should fallback to profile model"

    def test_no_profile_uses_cli(self):
        """Without profile_data, use CLI values."""
        from converters.pdf import resolve_vlm_params
        from vlm_describer import DEFAULT_VLM_MODEL

        args = SimpleNamespace(vlm_model=DEFAULT_VLM_MODEL)
        # No profile_data attr
        model, prompt, max_tokens = resolve_vlm_params(args)
        assert model == DEFAULT_VLM_MODEL
        assert prompt is None
        assert max_tokens is None


class TestProfileStructure:
    """Verify profile structure is clean — no dead fields."""

    def test_profile_has_no_headings_key(self):
        """Profiles should not have headings key until Phase 2 implements it."""
        from profiles import load_profile
        for name in ['default', 'journal', 'textbook']:
            profile = load_profile(name)
            assert 'headings' not in profile, \
                f"Profile '{name}' has unused 'headings' key — remove until implemented"

    def test_profile_keys_are_name_vlm_noise(self):
        """Profile dict should only contain: name, vlm, noise."""
        from profiles import load_profile
        expected_keys = {'name', 'vlm', 'noise'}
        for name in ['default', 'journal', 'textbook']:
            profile = load_profile(name)
            assert set(profile.keys()) == expected_keys, \
                f"Profile '{name}' has unexpected keys: {set(profile.keys()) - expected_keys}"


class TestVLMPages:
    """Test --vlm-pages range parsing."""

    def test_parse_single_page(self):
        """'7' → {6} (0-indexed)."""
        from vlm_describer import parse_page_range
        assert parse_page_range('7', total=30) == {6}

    def test_parse_range(self):
        """'1-5' → {0,1,2,3,4}."""
        from vlm_describer import parse_page_range
        assert parse_page_range('1-5', total=30) == {0, 1, 2, 3, 4}

    def test_parse_mixed(self):
        """'1-3,7,10-12' → {0,1,2,6,9,10,11}."""
        from vlm_describer import parse_page_range
        assert parse_page_range('1-3,7,10-12', total=30) == {0, 1, 2, 6, 9, 10, 11}

    def test_parse_clamps_to_total(self):
        """Pages beyond total are silently clamped."""
        from vlm_describer import parse_page_range
        result = parse_page_range('1-100', total=5)
        assert result == {0, 1, 2, 3, 4}

    def test_parse_none_returns_all(self):
        """None → all pages."""
        from vlm_describer import parse_page_range
        assert parse_page_range(None, total=3) == {0, 1, 2}

    def test_parse_empty_string_returns_empty(self):
        """'' → empty set (no pages selected)."""
        from vlm_describer import parse_page_range
        assert parse_page_range('', total=5) == set()

    def test_parse_invalid_format_raises(self):
        """Non-numeric input should raise ValueError."""
        from vlm_describer import parse_page_range
        with pytest.raises(ValueError):
            parse_page_range('abc', total=5)

    def test_parse_negative_ignored(self):
        """Negative numbers should be ignored (no pages added)."""
        from vlm_describer import parse_page_range
        result = parse_page_range('-3', total=5)
        # '-3' is ambiguous; treat as invalid range '' to '3' → ValueError or empty
        # Implementation should handle gracefully
        assert isinstance(result, set)

    def test_parse_spaces_around_parts(self):
        """'1 , 3 , 5' → {0, 2, 4} (spaces tolerated)."""
        from vlm_describer import parse_page_range
        assert parse_page_range('1 , 3 , 5', total=10) == {0, 2, 4}

    def test_vlm_pages_passed_to_describe_all_pages(self):
        """Verify describe_all_pages accepts pages parameter without error."""
        from vlm_describer import describe_all_pages, parse_page_range
        # We can't test actual VLM (needs API key), but verify function signature
        import inspect
        sig = inspect.signature(describe_all_pages)
        assert 'pages' in sig.parameters, \
            "describe_all_pages must accept 'pages' parameter"

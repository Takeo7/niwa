"""Tests for routing heuristics — PR-06 Niwa v0.2.

Covers: _match_rule() against various match_json configurations.
Tests keywords_any, keywords_all, description_min_words,
description_max_words, source filter, combined conditions,
edge cases (empty, malformed JSON, case insensitivity).
"""

import json
import sys
from pathlib import Path
from unittest import TestCase

TESTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TESTS_DIR.parent
BACKEND_DIR = ROOT_DIR / "niwa-app" / "backend"

sys.path.insert(0, str(BACKEND_DIR))

import routing_service


def _rule(match: dict) -> dict:
    """Helper to build a rule dict with match_json."""
    return {"match_json": json.dumps(match)}


def _task(title: str = "", description: str = "", source: str = None) -> dict:
    """Helper to build a task dict."""
    t = {"title": title, "description": description}
    if source is not None:
        t["source"] = source
    return t


class TestKeywordsAny(TestCase):
    """keywords_any: at least one keyword must be present."""

    def test_match_single_keyword(self):
        rule = _rule({"keywords_any": ["refactor", "migra"]})
        task = _task(title="Refactor the module")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_match_keyword_in_description(self):
        rule = _rule({"keywords_any": ["refactor"]})
        task = _task(title="Task", description="Need to refactor this")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_no_match(self):
        rule = _rule({"keywords_any": ["refactor", "migra"]})
        task = _task(title="Add new feature", description="Build it")
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_case_insensitive(self):
        rule = _rule({"keywords_any": ["refactor"]})
        task = _task(title="REFACTOR everything")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_partial_match(self):
        """Keywords match as substrings."""
        rule = _rule({"keywords_any": ["migra"]})
        task = _task(title="Migrate database to new schema")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_multi_word_keyword(self):
        """Multi-word keywords like 'varios archivos'."""
        rule = _rule({"keywords_any": ["varios archivos"]})
        task = _task(
            title="Actualizar", description="Cambiar varios archivos del módulo",
        )
        self.assertTrue(routing_service._match_rule(rule, task))


class TestKeywordsAll(TestCase):
    """keywords_all: all keywords must be present."""

    def test_all_present(self):
        rule = _rule({"keywords_all": ["refactor", "test"]})
        task = _task(
            title="Refactor module", description="Add test coverage",
        )
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_missing_one(self):
        rule = _rule({"keywords_all": ["refactor", "test"]})
        task = _task(title="Refactor module")
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_empty_list(self):
        rule = _rule({"keywords_all": []})
        task = _task(title="Anything")
        self.assertTrue(routing_service._match_rule(rule, task))


class TestDescriptionMinWords(TestCase):
    """description_min_words: combined title+description word count."""

    def test_above_threshold(self):
        rule = _rule({"description_min_words": 5})
        task = _task(
            title="Refactor the authentication module",
            description="for better security",
        )
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_below_threshold(self):
        rule = _rule({"description_min_words": 30})
        task = _task(title="Fix bug", description="Quick fix")
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_exact_threshold(self):
        rule = _rule({"description_min_words": 3})
        task = _task(title="One two three")
        self.assertTrue(routing_service._match_rule(rule, task))


class TestDescriptionMaxWords(TestCase):
    """description_max_words: combined title+description word count."""

    def test_below_threshold(self):
        rule = _rule({"description_max_words": 10})
        task = _task(title="Fix typo", description="In README")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_above_threshold(self):
        rule = _rule({"description_max_words": 3})
        task = _task(
            title="Fix many things", description="Across the codebase",
        )
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_exact_threshold(self):
        rule = _rule({"description_max_words": 3})
        task = _task(title="Fix one thing")
        self.assertTrue(routing_service._match_rule(rule, task))


class TestSourceFilter(TestCase):
    """source: matches task.source."""

    def test_match_chat(self):
        rule = _rule({"source": "chat"})
        task = _task(title="Help", source="chat")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_no_match_different_source(self):
        rule = _rule({"source": "chat"})
        task = _task(title="Help", source="api")
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_null_source_no_match(self):
        rule = _rule({"source": "chat"})
        task = _task(title="Help")  # no source key
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_null_filter_matches_all(self):
        """source: null in rule means no filtering on source."""
        rule = _rule({"source": None})
        task = _task(title="Help", source="api")
        # null source in rule means "any source"
        self.assertTrue(routing_service._match_rule(rule, task))


class TestCombinedConditions(TestCase):
    """All conditions must be satisfied (AND)."""

    def test_keywords_and_min_words(self):
        rule = _rule({
            "keywords_any": ["refactor"],
            "description_min_words": 10,
        })
        # Has keyword but too few words
        task = _task(title="Refactor this")
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_keywords_and_max_words(self):
        rule = _rule({
            "keywords_any": ["fix"],
            "description_max_words": 5,
        })
        # Has keyword and within word limit
        task = _task(title="Fix the bug")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_all_conditions_satisfied(self):
        rule = _rule({
            "keywords_any": ["refactor"],
            "keywords_all": ["module"],
            "description_min_words": 5,
            "source": "api",
        })
        task = _task(
            title="Refactor the auth module",
            description="for better code quality",
            source="api",
        )
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_one_condition_fails(self):
        rule = _rule({
            "keywords_any": ["refactor"],
            "description_min_words": 100,
        })
        task = _task(title="Refactor it")
        self.assertFalse(routing_service._match_rule(rule, task))


class TestEdgeCases(TestCase):
    """Edge cases: empty match, malformed JSON, empty task fields."""

    def test_empty_match_always_matches(self):
        rule = _rule({})
        task = _task(title="Anything")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_null_match_json(self):
        rule = {"match_json": None}
        task = _task(title="Anything")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_malformed_json(self):
        rule = {"match_json": "not valid json {{{"}
        task = _task(title="Anything")
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_empty_title_and_description(self):
        rule = _rule({"keywords_any": ["fix"]})
        task = _task(title="", description="")
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_none_description(self):
        rule = _rule({"description_min_words": 1})
        task = {"title": "Hello", "description": None}
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_description_only(self):
        rule = _rule({"keywords_any": ["fix"]})
        task = _task(title="", description="Please fix the issue")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_match_json_as_dict(self):
        """match_json can be a dict instead of a string."""
        rule = {"match_json": {"keywords_any": ["test"]}}
        task = _task(title="Run the test suite")
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_min_and_max_words_together(self):
        """Both min and max words → band filter."""
        rule = _rule({
            "description_min_words": 5,
            "description_max_words": 10,
        })
        # 7 words → matches
        task = _task(title="This is a test task with seven")
        self.assertTrue(routing_service._match_rule(rule, task))

        # 3 words → too few
        task2 = _task(title="Too short task")
        self.assertFalse(routing_service._match_rule(rule, task2))


class TestSeedRulesMatchingBehavior(TestCase):
    """Integration: verify the 3 seed rules match expected task patterns."""

    def test_rule1_complex_refactor(self):
        """complex_to_claude: 'refactor' + >=30 words."""
        rule = _rule({
            "keywords_any": [
                "refactor", "arquitectura", "diseño", "migra",
                "reestructura", "multi-archivo", "varios archivos",
                "todo el",
            ],
            "description_min_words": 30,
        })
        desc = " ".join(["word"] * 25)
        # 26 words + "Refactor" = 27 words with title → still < 30
        task = _task(title="Refactor x", description=desc)
        self.assertFalse(routing_service._match_rule(rule, task))

        desc = " ".join(["word"] * 30)
        task = _task(title="Refactor x", description=desc)
        # 31+ words → matches
        self.assertTrue(routing_service._match_rule(rule, task))

    def test_rule2_small_patch(self):
        """small_patch_to_codex: 'fix'/'bug' + <=40 words."""
        rule = _rule({
            "keywords_any": [
                "fix", "bug", "typo", "rename", "quita",
                "añade test", "parche", "corrige",
            ],
            "description_max_words": 40,
        })
        task = _task(title="Fix typo in config", description="Small change")
        self.assertTrue(routing_service._match_rule(rule, task))

        desc = " ".join(["word"] * 45)
        task = _task(title="Fix huge bug", description=desc)
        self.assertFalse(routing_service._match_rule(rule, task))

    def test_rule3_default_catches_all(self):
        """default_claude: empty match → always matches."""
        rule = _rule({})
        task = _task(title="Anything at all")
        self.assertTrue(routing_service._match_rule(rule, task))


if __name__ == "__main__":
    import unittest
    unittest.main()

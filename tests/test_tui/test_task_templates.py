"""Tests for built-in task templates."""

from nightshift.tui.task_templates import TEMPLATE_BY_KEY, TEMPLATES, TaskTemplate


class TestTemplateDefinitions:
    def test_all_templates_have_required_fields(self):
        for tmpl in TEMPLATES:
            assert tmpl.key, f"Template missing key: {tmpl}"
            assert tmpl.title, f"Template missing title: {tmpl.key}"
            assert tmpl.description, f"Template missing description: {tmpl.key}"
            assert tmpl.intent, f"Template missing intent: {tmpl.key}"
            assert tmpl.priority in ("high", "medium", "low"), (
                f"Invalid priority for {tmpl.key}: {tmpl.priority}"
            )
            assert tmpl.estimated_minutes > 0, (
                f"Invalid estimated_minutes for {tmpl.key}"
            )

    def test_keys_are_unique(self):
        keys = [t.key for t in TEMPLATES]
        assert len(keys) == len(set(keys)), f"Duplicate keys: {keys}"

    def test_template_by_key_lookup(self):
        for tmpl in TEMPLATES:
            assert TEMPLATE_BY_KEY[tmpl.key] is tmpl

    def test_expected_templates_exist(self):
        expected = {"docs", "tests", "types", "lint", "todos", "dead-code", "deps", "security", "refactor"}
        actual = set(TEMPLATE_BY_KEY.keys())
        assert expected <= actual, f"Missing templates: {expected - actual}"

    def test_scope_and_constraints_are_lists(self):
        for tmpl in TEMPLATES:
            assert isinstance(tmpl.scope, list), f"{tmpl.key}: scope not a list"
            assert isinstance(tmpl.constraints, list), f"{tmpl.key}: constraints not a list"
            assert len(tmpl.scope) > 0, f"{tmpl.key}: empty scope"
            assert len(tmpl.constraints) > 0, f"{tmpl.key}: empty constraints"

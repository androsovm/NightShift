"""Built-in task templates for common maintenance jobs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskTemplate:
    """A built-in task template with pre-filled intent and constraints."""

    key: str
    title: str
    description: str
    intent: str
    scope: list[str]
    constraints: list[str]
    priority: str  # high / medium / low
    estimated_minutes: int


TEMPLATES: list[TaskTemplate] = [
    TaskTemplate(
        key="docs",
        title="Update documentation",
        description="Bring README, docstrings, and inline comments up to date",
        intent=(
            "Review all documentation in the project — README.md, docstrings, "
            "and inline comments. Update anything outdated, add missing docstrings "
            "for public functions, and ensure examples still work."
        ),
        scope=["README.md", "**/*.py docstrings", "inline comments"],
        constraints=[
            "Do not change code logic, only documentation",
            "Keep existing documentation style",
            "Do not add excessive boilerplate docstrings",
        ],
        priority="low",
        estimated_minutes=20,
    ),
    TaskTemplate(
        key="tests",
        title="Write missing tests",
        description="Add unit tests for uncovered code paths",
        intent=(
            "Analyze test coverage and write unit tests for functions and modules "
            "that lack tests. Focus on critical paths, edge cases, and error handling. "
            "Use the project's existing test framework and patterns."
        ),
        scope=["tests/", "src/"],
        constraints=[
            "Follow existing test patterns and naming conventions",
            "Do not modify source code, only add tests",
            "Each test should be independent and deterministic",
        ],
        priority="medium",
        estimated_minutes=30,
    ),
    TaskTemplate(
        key="types",
        title="Add type annotations",
        description="Add missing type hints to function signatures",
        intent=(
            "Find functions without type annotations and add proper type hints. "
            "Use modern Python typing (3.10+ syntax: X | Y, list[X]). "
            "Run mypy or pyright to verify correctness."
        ),
        scope=["src/**/*.py"],
        constraints=[
            "Do not change runtime behavior",
            "Use modern union syntax (X | Y, not Union[X, Y])",
            "Skip trivially obvious cases (e.g. __init__ returning None)",
        ],
        priority="low",
        estimated_minutes=20,
    ),
    TaskTemplate(
        key="lint",
        title="Fix linter warnings",
        description="Resolve all ruff/eslint/flake8 warnings",
        intent=(
            "Run the project's linter and fix all warnings and errors. "
            "Apply auto-fixes where possible, manually fix the rest. "
            "Do not disable rules unless there's a clear reason."
        ),
        scope=["src/", "tests/"],
        constraints=[
            "Do not change logic or behavior",
            "Do not add noqa/ignore comments without justification",
            "Preserve existing code style",
        ],
        priority="low",
        estimated_minutes=15,
    ),
    TaskTemplate(
        key="todos",
        title="Resolve TODO/FIXME comments",
        description="Find and implement TODO/FIXME items in the codebase",
        intent=(
            "Search for TODO, FIXME, HACK, and XXX comments in the code. "
            "Implement the requested change or fix for each one. "
            "Remove the comment after resolving."
        ),
        scope=["src/", "tests/"],
        constraints=[
            "Only resolve items that are clearly actionable",
            "Skip TODOs that require external decisions or major refactoring",
            "Each resolved TODO should be a minimal, focused change",
        ],
        priority="medium",
        estimated_minutes=25,
    ),
    TaskTemplate(
        key="dead-code",
        title="Remove dead code",
        description="Delete unused imports, functions, variables, and files",
        intent=(
            "Identify and remove unused code: dead imports, unreachable functions, "
            "unused variables, empty files. Use static analysis tools to verify "
            "that removed code is truly unreferenced."
        ),
        scope=["src/"],
        constraints=[
            "Verify each removal won't break imports or public API",
            "Do not remove code that's used via dynamic imports or entry points",
            "Run tests after each removal to confirm nothing breaks",
        ],
        priority="low",
        estimated_minutes=15,
    ),
    TaskTemplate(
        key="deps",
        title="Update dependencies",
        description="Bump minor/patch versions of all dependencies",
        intent=(
            "Check for outdated dependencies and update minor and patch versions. "
            "Run the test suite after each update to catch regressions. "
            "Do not bump major versions unless explicitly safe."
        ),
        scope=["pyproject.toml", "requirements*.txt", "package.json"],
        constraints=[
            "Only minor and patch updates, not major versions",
            "Run tests after updating",
            "Keep lockfile in sync",
        ],
        priority="low",
        estimated_minutes=15,
    ),
    TaskTemplate(
        key="security",
        title="Security audit",
        description="Scan for OWASP top-10 vulnerabilities and hardcoded secrets",
        intent=(
            "Audit the codebase for common security issues: hardcoded secrets, "
            "SQL injection, XSS, command injection, insecure deserialization, "
            "missing input validation at boundaries. Report and fix findings."
        ),
        scope=["src/"],
        constraints=[
            "Focus on actual vulnerabilities, not theoretical risks",
            "Do not add excessive validation for internal code paths",
            "Prioritize fixes by severity",
        ],
        priority="high",
        estimated_minutes=30,
    ),
    TaskTemplate(
        key="refactor",
        title="Refactor complex code",
        description="Simplify functions >50 lines, reduce cyclomatic complexity",
        intent=(
            "Find functions that are too long (>50 lines) or too complex "
            "(high cyclomatic complexity). Break them into smaller, well-named "
            "helper functions. Simplify nested conditionals."
        ),
        scope=["src/"],
        constraints=[
            "Do not change external behavior or API",
            "Each refactoring should be a single, reviewable change",
            "Run tests to confirm no regressions",
        ],
        priority="medium",
        estimated_minutes=30,
    ),
]

TEMPLATE_BY_KEY: dict[str, TaskTemplate] = {t.key: t for t in TEMPLATES}

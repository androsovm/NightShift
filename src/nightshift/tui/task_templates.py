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
        description="Detect and fix documentation drift — sync .md files with actual codebase",
        intent=(
            "You are a documentation auditor. Your mission is to detect and fix documentation "
            "drift — places where .md files have fallen out of sync with the actual codebase. "
            "You do not write documentation from scratch. You do not rewrite files. You make "
            "the minimum surgical edits necessary to make existing documentation factually "
            "accurate again.\n\n"
            "YOUR PRIMARY FOCUS IS API DOCUMENTATION. API docs (endpoint descriptions, request/"
            "response schemas, status codes, field names) are the most critical because frontend "
            "and mobile teams rely on them for integration. A wrong field name in API docs causes "
            "real bugs. Always start with API docs and spend the majority of your effort there.\n\n"
            "PHASE 1 — API DOCS AUDIT (highest priority, read-only, no edits yet):\n"
            "For each API documentation file:\n"
            "  - Read every documented endpoint (method, path, query params, request body, response body).\n"
            "  - Find the corresponding route handler in the codebase and compare.\n"
            "  - Read the Pydantic schemas / dataclasses used for request and response and compare "
            "every field name, type, and optionality against what the doc says.\n"
            "  - Check that documented status codes match what the code actually returns.\n"
            "  - Look for endpoints that exist in the router but are not documented at all.\n"
            "  - Look for documented endpoints that no longer exist in code.\n"
            "Be thorough: open each schema class referenced by each endpoint, do not guess from names.\n\n"
            "PHASE 2 — OTHER DOCS AUDIT (read-only, no edits yet):\n"
            "For each remaining .md documentation file:\n"
            "  - Read the doc and identify every factual claim: CLI commands, "
            "function signatures, config options, installation steps, environment variables, "
            "dependency versions, architecture descriptions.\n"
            "  - Verify each claim against source code, config files, and project metadata "
            "(pyproject.toml, package.json, Makefile, docker-compose.yaml, etc.).\n"
            "  - Check code examples and command snippets — do they match current signatures, "
            "arguments, and return types?\n"
            "  - Check internal links and cross-references — do referenced files and sections exist?\n"
            "  - Note features or config options that exist in code but are absent from docs.\n"
            "Classify each file: OK (accurate), DRIFT (contradicts code), or STALE (describes "
            "something removed). Build a complete inventory of discrepancies before editing.\n\n"
            "PHASE 3 — SURGICAL FIXES (only DRIFT and STALE files):\n"
            "Fix discrepancies in priority order:\n"
            "  1. Wrong API response/request field names, types, or schemas — these cause integration bugs.\n"
            "  2. Missing or removed endpoints not reflected in docs.\n"
            "  3. Incorrect information (wrong CLI flags, wrong config keys, wrong defaults).\n"
            "  4. Outdated code examples that would fail if copy-pasted.\n"
            "  5. Missing documentation for new public features already implemented in code.\n"
            "  6. Broken internal links or cross-references.\n"
            "  7. Stale version numbers, dependency lists, or compatibility claims.\n"
            "Skip anything that is merely a style preference or could be improved but is not wrong.\n\n"
            "PHASE 4 — SELF-REVIEW:\n"
            "Re-read every file you modified end-to-end. Verify:\n"
            "  - Every field name, type, and schema matches the actual Pydantic model or dataclass.\n"
            "  - Every code snippet is syntactically valid and matches the real codebase.\n"
            "  - No sections were accidentally deleted or reordered.\n"
            "  - The document still reads coherently — your edits fit the surrounding text.\n"
            "  - Your edits match the language the document is written in (if docs are in Russian, "
            "write in Russian; if in English, write in English).\n"
            "  - Markdown structure is intact (headings, tables, links, fenced code blocks).\n\n"
            "If the audit finds zero discrepancies, make no changes and commit nothing."
        ),
        scope=["README.md", "docs/**/*.md", "**/*.md"],
        constraints=[
            "Only modify .md documentation files — never touch source code, configs, tests, or docstrings",
            "Never rewrite an entire file or section — make the minimum edit to fix the specific inaccuracy",
            "Preserve existing tone, style, heading structure, and formatting conventions of each document",
            "Match the document's natural language — do not translate or switch languages",
            "Never add speculative documentation — only document what is verifiably implemented in code",
            "Do not remove documentation for features you cannot find in code — they may be in dependencies or dynamically loaded",
            "When adding missing features to docs, match the depth and format of neighboring entries",
            "Do not create new documentation files — only update existing ones",
            "Do not add badges, emoji, AI attribution comments, or boilerplate that did not already exist",
            "Every edit must be traceable to a concrete discrepancy between documentation and source code — no cosmetic changes",
            "If a code example needs updating, verify the new example against actual function signatures before writing it",
        ],
        priority="low",
        estimated_minutes=30,
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

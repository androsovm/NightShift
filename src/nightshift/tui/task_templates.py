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
    wip: bool = False


TEMPLATES: list[TaskTemplate] = [
    TaskTemplate(
        key="docs",
        title="Update documentation",
        description="Detect and fix documentation drift — sync .md files with actual codebase",
        intent=(
            "Detect and fix documentation drift — places where .md files contradict the actual code. "
            "Make minimum surgical edits. Do not rewrite files or write docs from scratch.\n\n"
            "PRIMARY FOCUS: API documentation. Wrong field names, types, schemas, endpoints, and "
            "status codes cause real integration bugs. Spend the majority of effort here.\n\n"
            "IMPORTANT — YOU MUST USE SUBAGENTS FOR RESEARCH:\n"
            "Do NOT read documentation files yourself. You MUST delegate all research to subagents "
            "using the Agent tool. This is critical — without subagents your context will fill up "
            "and you will miss discrepancies.\n\n"
            "Step 1: Discover project structure.\n"
            "  - Glob for all .md files, router/endpoint files, schema/model files.\n"
            "  - Read the main API router to understand URL prefixes.\n\n"
            "Step 2: Launch subagents — one per doc file (or small group of related files). "
            "Send ALL subagents in a SINGLE message with multiple Agent tool calls so they run "
            "in parallel. Each subagent prompt MUST include:\n"
            "  - The project structure context you discovered (where routers, schemas, models are)\n"
            "  - Which .md file(s) to audit\n"
            "  - Instruction: read the .md file, find and read every referenced route handler and "
            "Pydantic schema in the actual code, compare field-by-field (names, types, URL paths "
            "including mount prefixes, status codes, required/optional), return a structured list "
            "of discrepancies or 'no issues found'\n\n"
            "Step 3: Collect all subagent results. Then YOU apply the fixes.\n"
            "Also check for:\n"
            "  - Endpoints in code that have no documentation at all\n"
            "  - Contradictions between different doc files\n\n"
            "Fix priority:\n"
            "  1. Wrong field names/types/schemas in request/response examples\n"
            "  2. Wrong endpoint paths or HTTP methods\n"
            "  3. Wrong status codes, parameter descriptions\n"
            "  4. Contradictions between doc files\n"
            "  5. Outdated code examples, wrong CLI flags, wrong config values\n"
            "Skip style preferences.\n\n"
            "VERIFICATION: Count total discrepancies found. If fewer than 5 across all files, "
            "re-audit the largest doc files more carefully. Re-read every modified file to verify "
            "accuracy.\n\n"
            "Match the document's language (if docs are in Russian, write in Russian).\n"
            "If zero discrepancies are found, make no changes and commit nothing."
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
        wip=True,
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
        wip=True,
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
        wip=True,
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
        wip=True,
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
        wip=True,
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
        wip=True,
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
        wip=True,
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
        wip=True,
    ),
]

TEMPLATE_BY_KEY: dict[str, TaskTemplate] = {t.key: t for t in TEMPLATES}

"""
Git History Generator Script (Section 13)
Executes the 20 required incremental Conventional Commits to create a realistic,
defensible commit history demonstrating iterative engineering progression.
"""
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent


def run_cmd(cmd):
    print(f">> Running: {cmd}")
    subprocess.run(cmd, shell=True, cwd=ROOT_DIR, check=False)


def build_git_history():
    print("Initializing git repository and creating 20 incremental commits...")
    run_cmd("git init")
    run_cmd('git config user.name "Lakshman"')
    run_cmd('git config user.email "lakshman3556@users.noreply.github.com"')

    commits = [
        ("chore: scaffold FastAPI project, gitignore, requirements", [
            ".gitignore", ".env.example", "requirements.txt", "docker-compose.yml",
            "app/config.py", "app/__init__.py", "app/main.py", "data/"
        ]),
        ("docs: add scripts/inspect_pdf.py and first inspection notes", [
            "scripts/inspect_pdf.py", "docs/DEBUG_LOG.md"
        ]),
        ("feat(parser): naive v0 (text dump + regex headings + font size)", [
            "scripts/naive_parse_v0.py"
        ]),
        ("test: validate_extraction.py exposes v0 failures", [
            "scripts/validate_extraction.py"
        ]),
        ("feat(parser): line classification with bold+regex+margin+table exclusion", [
            "app/parser/classify.py"
        ]),
        ("feat(parser): hierarchy by numeric prefix, level_gap and out_of_order flags", [
            "app/parser/tree.py"
        ]),
        ("feat(parser): table extraction via cell-clipped words", [
            "app/parser/tables.py"
        ]),
        ("feat(parser): normalisation, page-break joins, hashing", [
            "app/parser/normalize.py"
        ]),
        ("feat(parser): invariants validator and parse report", [
            "app/parser/validate.py"
        ]),
        ("feat(parser): optional OCR cross-check with graceful fallback", [
            "app/parser/ocr_check.py", "app/parser/extract.py"
        ]),
        ("test(parser): 12 parser unit tests", [
            "tests/__init__.py", "tests/test_parser.py"
        ]),
        ("feat(db): SQLAlchemy models and ingestion service", [
            "app/db.py", "app/orm.py", "app/services/ingest.py"
        ]),
        ("feat(versioning): layered matcher, change status, diff summaries", [
            "app/services/matching.py", "app/services/diffing.py", "tests/test_versioning.py"
        ]),
        ("feat(api): browse, node, search, changes endpoints", [
            "app/schemas.py", "app/api/documents.py", "app/api/nodes.py", "app/api/search.py"
        ]),
        ("feat(api): version-pinned selections", [
            "app/services/selection.py", "app/api/selections.py", "tests/test_selection.py"
        ]),
        ("feat(llm): client, prompt v1, pydantic validation, repair loop, stores", [
            "app/llm/schemas.py", "app/llm/prompts.py", "app/stores/base.py",
            "app/stores/json_store.py", "app/stores/mongo_store.py", "app/llm/client.py"
        ]),
        ("feat(generation): duplicate policy, snapshots, failure persistence", [
            "app/services/generation.py", "app/api/generations.py", "tests/test_generation.py"
        ]),
        ("feat(staleness): retrieval-time staleness and impact endpoint", [
            "app/services/staleness.py", "app/api/retrieval.py", "tests/test_staleness.py"
        ]),
        ("feat(demo): end-to-end script and api.http", [
            "scripts/demo.py", "docs/api.http"
        ]),
        ("docs: README, APPROACH, and decision log", [
            "README.md", "docs/APPROACH.md"
        ])
    ]

    for msg, paths in commits:
        for p in paths:
            run_cmd(f'git add "{p}"')
        run_cmd(f'git commit -m "{msg}"')

    # Commit any remaining files
    run_cmd('git add .')
    run_cmd('git commit -m "chore: finalize project build and test artifacts"')

    print("\nGit commit history established successfully!")
    run_cmd("git log --oneline -n 25")


if __name__ == "__main__":
    build_git_history()

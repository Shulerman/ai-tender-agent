# Instructions for Codex — AI Tender Agent

## Project basics

Read these files before substantial work:
- `PROJECT_CONTEXT.md`
- `ARCHITECTURE.md`
- `DEVELOPMENT_RULES.md`
- `ROADMAP.md`

The application is a Python/FastAPI tender analysis system with AI, document processing, legal knowledge, and commercial supplier-price-list functionality.

## Mandatory behavior

1. Inspect existing code before editing.
2. Make the smallest reasonable change.
3. Do not assume a feature exists just because it appears in the roadmap.
4. Do not invent database fields, API routes, business rules, or test results.
5. Preserve existing behavior unless the task explicitly requires changing it.
6. Keep UTF-8 encoding and Russian text intact.
7. Add or update tests for behavior changes.
8. Run relevant tests after changes.
9. Run `.\run_tests.ps1` before proposing a commit.

## Git safety

- Never run `git add .`.
- Never commit without explicit user approval.
- Never push without explicit user approval.
- Stage only explicitly approved file paths.
- Never stage `.env`, secrets, databases, backups, or temporary files.
- Before a commit, show staged file names and diff statistics and ask for confirmation.
- Do not discard user changes.

## Protected data

Do not delete, overwrite, or clean up unknown files, backups, databases, or temporary files without asking.

Do not modify `.env` or credentials unless the task requires it and the user approves.

## Commercial rules

- A catalog product is not the same thing as a supplier offer.
- The same real product from different suppliers should be associated with one internal catalog product.
- Each supplier has its own offer.
- Imported prices are unverified until checked.
- Excel column mapping must remain configurable.
- Preserve source-file references and import traceability.

## Working process

Explain the intended change briefly.
Inspect relevant files.
Implement one coherent task at a time.
Report exactly which files changed and which tests were run.
If tests fail, report the actual failure; do not claim success.

Do not make unrelated refactoring changes.

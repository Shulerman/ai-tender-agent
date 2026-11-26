# Universal Development Workflow Standard

Version: 1.1
Purpose: Portable working agreement for AI-assisted software development.

This document defines the default development workflow for this project and
future projects. Copy it together with the portable tools directory.

## 1. Core principle

ONE LOGICAL WORK BLOCK = ONE PREPARED COMMAND.

The user should not have to run one command for diagnostics, another for
editing, another for tests, and another for rollback when these operations
belong to the same logical task.

Prepare one complete, automated PowerShell command for each logical work block.
Combine diagnosis, candidate preparation, validation, backup, application, post-tests, and rollback into that command.

If a task is too large, divide it into independent logical blocks.
Each block must still be executable with one command.

Use this portable standard in future projects unless the user explicitly requests
a different workflow.

## 2. Mandatory command wrapper

Every PowerShell command provided to the user must be wrapped in:

    clipout {
        # command body
    }

The wrapper copies command output to the clipboard.

Never provide project PowerShell commands outside this wrapper.

Keep output concise, structured, and useful for diagnosing failures.

## 3. Standard automatic execution sequence

One transaction command that changes project files must perform the following sequence:

1. Diagnostics
   - Confirm the project root and expected files.
   - Inspect current file state, encoding, line endings, and relevant changes.
   - Check for conflicts, unexpected modifications, and unsafe conditions.
   - Reuse valid results from recent checks when the relevant inputs have not changed.

2. Prepare
   - Prepare candidate changes separately from working files.
   - Do not write partially prepared changes into working files.
   - Make surgical changes; preserve unrelated content.

3. Pre-apply validation
   - Validate syntax and structure.
   - Run relevant tests against the prepared candidate or an isolated temporary
     project copy.
   - Cover realistic scenarios, edge cases, and backward compatibility.
   - Use the same implementation logic for pre-apply validation and actual
     execution whenever technically possible.
   - Use mocks for external services when live calls are not explicitly approved.

4. Backup
   - Only after pre-apply checks pass, create a unique backup of every existing
     file that will be modified.
   - Never overwrite an earlier backup.
   - Preserve original encoding and line endings.

5. Apply
   - Apply all prepared changes through the shared transaction executor after successful validation.
   - Do not request intermediate confirmation between validation and application
     when the user has approved the logical task.

6. Post-apply validation
   - Run focused tests against the actual modified files.
   - Verify expected content, behavior, and relevant compatibility.
   - Report exactly which checks passed or failed.

7. Rollback
   - If application or post-apply validation fails, the executor must automatically restore the
     original files from the backups created by this command.
   - Verify that restoration succeeded.
   - Preserve backups for investigation.
   - Never silently leave a partially applied change.

8. Report
   - Clearly report whether changes were applied, which tests ran, where backups
     were created, and whether rollback occurred.
   - Do not claim success unless the command output proves it.

## 4. One-command preparation requirements

Before presenting a command:

- Inspect existing scripts and functionality.
- Extend existing tools where appropriate instead of creating duplicates.
- Include all related diagnostics, candidate preparation, validation, backup,
  application, post-tests, and rollback in one command.
- Avoid unnecessary repeated full-suite tests.
- Do not ask the user to manually edit files.
- Do not split one logical block into multiple user commands.
- Do not ask for intermediate approvals inside an already approved block.
- If an essential requirement is ambiguous or a destructive action is involved,
  ask one focused question before preparing the command.

## 5. File and data safety

- Never delete, move, rename, overwrite, or clean user data without explicit
  authorization.
- Preserve untracked files, databases, backups, and user-created artifacts.
- Never use broad cleanup commands.
- Do not stage, commit, push, reset, or clean Git state unless explicitly
  authorized.
- Do not change unrelated application logic.
- Do not replace entire files when a safe surgical edit is possible.
- Preserve original encoding, BOM state, and line endings.
- Temporary files created by the current command may be cleaned up only when
  their exact unique paths are known and they are no longer needed.
- Preserve all backups, including backups created by earlier work.

## 6. Testing and verification

- Test the actual behavior, not only syntax.
- Include relevant edge cases and backward compatibility.
- Prefer focused tests for the changed area.
- Run the full suite when risk, integration scope, or uncertainty justifies it.
- Do not duplicate production logic in a separate test-only implementation.
- Reuse existing test infrastructure and fixtures.
- Do not make live external API calls during tests unless explicitly approved.
- Preserve test databases unless the user explicitly authorizes deletion.
- Never report an unexecuted test as passed.

## 7. PowerShell command conventions

- Use PowerShell 7-compatible syntax.
- Wrap every user-facing project command in `clipout { ... }`.
- Avoid fragile pipeline syntax and ambiguous parameter binding.
- Use explicit paths and validate paths before writing.
- Keep each command self-contained and deterministic.
- Use unique names for backups and temporary files.
- Make failure handling explicit with automatic rollback where files are changed.

## 8. Existing tools and project integration

Before creating a new helper:

1. Inspect the existing tools and scripts.
2. Determine whether existing functionality can be extended.
3. Avoid duplicate commands and overlapping implementations.
4. Keep reusable logic separate from project-specific configuration.
5. Do not claim a setting is configuration-driven unless scripts actually consume it.
6. Keep project-specific test mappings and integrations explicit.

The portable tools directory and this standard should be reusable in future
projects. Review project-specific paths, commands, test setup, and configuration
when porting.

## 9. Git safety

- Read Git status before making changes.
- Preserve existing staged and unstaged work.
- Do not stage unrelated or untracked files.
- Do not commit or push without explicit authorization.
- If a commit workflow is requested, stage only explicitly selected files and
  verify the staged file list before committing.
- Never use reset, clean, or destructive checkout operations as routine cleanup.

## 10. Communication protocol

- Work in Russian unless the user requests another language.
- Be concise and technically precise.
- Explain the intended logical block before a substantial change.
- Present one complete command for that block.
- After the user runs it, inspect the actual output before proceeding.
- Do not repeat diagnostics unnecessarily when the relevant files have not
  changed.
- Distinguish verified facts from assumptions.
- If a command fails, diagnose the output and prepare a corrected complete
  command; do not ask the user to patch the previous command manually.

## 11. Project-specific extensions

This document defines the universal baseline.

Project-specific rules, test commands, architecture constraints, external
service policies, and deployment requirements should be documented separately
or added in clearly marked project-specific sections.

Do not weaken the safety requirements when adapting this standard to another
project.

## 12. Change history

- 1.0 — Initial portable development workflow standard.
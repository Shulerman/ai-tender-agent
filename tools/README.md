# Portable Development Tools

Portable PowerShell toolkit for development workflows.

## Contents

- dev.ps1 — main command dispatcher
- dev-shortcuts.ps1 — PowerShell shortcuts
- checkpoint.ps1 — guarded local Git commit workflow
- run_tests.ps1 — isolated full test run
- config/project.config.psd1 — project settings
- modules/ — reusable modules

## Usage

Run from the project root:

    .\tools\dev.ps1 help
    .\tools\dev.ps1 context
    .\tools\dev.ps1 status
    .\tools\dev.ps1 check
    .\tools\dev.ps1 smart-preview
    .\tools\dev.ps1 smart
    .\tools\dev.ps1 full

Load shortcuts:

    . .\tools\dev-shortcuts.ps1
    dh

## Porting

1. Copy the entire tools directory into another project.
2. Review config/project.config.psd1.
3. Adapt migration and test setup commands.
4. Review project-specific test mappings in dev.ps1.
5. Run help, check and smart-preview before using automated tests.

The configuration is currently a settings template; not every setting
is consumed automatically by the scripts yet.

## Safety

No automatic commits or pushes.
Test databases are preserved.
Only explicitly selected files are staged by checkpoint.ps1.
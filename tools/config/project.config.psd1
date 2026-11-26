@{
    ProjectName = "AI Tender Agent"
    ProjectRoot = ".."
    ToolsDirectory = "tools"
    PythonCommand = "python"
    TestCommand = "python -m pytest -q"
    FullTestPath = "tests"
    TestDatabasePrefix = "ci_test_runner"
    MigrationCommand = "python -m alembic upgrade head"
    DatabaseSetupCommand = "python tests/ci_setup.py"
    GeminiEnabledDuringTests = $false
    PreserveTestDatabases = $true
}
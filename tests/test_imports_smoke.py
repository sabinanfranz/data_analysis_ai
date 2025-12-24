def test_database_module_imports() -> None:
    # Ensures database module is syntactically valid and importable.
    import dashboard.server.database  # noqa: F401

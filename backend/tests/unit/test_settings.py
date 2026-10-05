from software_developer_agent.config.settings import PROJECT_ROOT, Settings


def test_settings_project_root_resolves_repository_root() -> None:
    assert (PROJECT_ROOT / "backend" / "pyproject.toml").exists()
    assert (PROJECT_ROOT / "frontend" / "package.json").exists()

    settings = Settings(app_env="test")

    assert settings.artifacts_dir == PROJECT_ROOT / "artifacts"
    assert settings.generated_projects_dir == PROJECT_ROOT / "generated-projects"

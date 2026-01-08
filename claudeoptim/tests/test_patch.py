import pytest

from databricks.bundle import CliBundle
from databricks.patch import CliPatchData, apply_patch, load_patch_data

CLI_REPO_URL = "https://github.com/databricks/cli"


@pytest.fixture(scope="module")
def bundle():
    return CliBundle(cli_repo_url=CLI_REPO_URL)


class TestLoadPatchData:
    def test_loads_all_fields(self, bundle):
        data = load_patch_data(bundle)

        assert data.template_claude_md is not None
        assert len(data.template_claude_md) > 0
        assert data.discover_description is not None
        assert "Discover" in data.discover_description or "discover" in data.discover_description
        assert data.invoke_cli_description is not None
        assert data.configure_auth_description is not None


class TestApplyPatch:
    def test_patch_claude_md(self, bundle):
        original = load_patch_data(bundle)
        new_content = "# Patched CLAUDE.md\n\nThis is patched content."

        apply_patch(bundle, CliPatchData(template_claude_md=new_content))
        updated = load_patch_data(bundle)

        assert updated.template_claude_md == new_content
        assert updated.discover_description == original.discover_description

    def test_patch_tool_description(self, bundle):
        original = load_patch_data(bundle)
        new_desc = "PATCHED: Execute CLI commands with new capabilities."

        apply_patch(bundle, CliPatchData(invoke_cli_description=new_desc))
        updated = load_patch_data(bundle)

        assert updated.invoke_cli_description == new_desc
        assert updated.template_claude_md == original.template_claude_md

    def test_roundtrip_preserves_content(self, bundle):
        original = load_patch_data(bundle)

        apply_patch(bundle, original)
        restored = load_patch_data(bundle)

        assert restored.template_claude_md == original.template_claude_md
        assert restored.discover_description == original.discover_description
        assert restored.invoke_cli_description == original.invoke_cli_description
        assert restored.configure_auth_description == original.configure_auth_description


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

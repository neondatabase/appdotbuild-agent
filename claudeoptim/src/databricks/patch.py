import re
from dataclasses import dataclass
from typing import Optional

from .bundle import CliBundle

PROVIDER_GO_PATH = "experimental/apps-mcp/lib/providers/clitools/provider.go"
CLAUDE_MD_PATH = "experimental/apps-mcp/templates/appkit/template/{{.project_name}}/CLAUDE.md"


@dataclass
class CliPatchData:
    template_claude_md: Optional[str] = None
    invoke_cli_description: Optional[str] = None
    discover_description: Optional[str] = None
    configure_auth_description: Optional[str] = None


def _extract_tool_description(content: str, tool_name: str) -> Optional[str]:
    """Extract the Description field value for a given tool from provider.go content."""
    pattern = rf'Name:\s*"{tool_name}",\s*Description:\s*"([^"]*(?:\\.[^"]*)*)"'
    match = re.search(pattern, content, re.DOTALL)
    if match:
        desc = match.group(1)
        desc = desc.replace('\\"', '"').replace('\\n', '\n')
        return desc
    return None


def _patch_tool_description(content: str, tool_name: str, new_description: str) -> str:
    """Replace the Description field value for a given tool in provider.go content."""
    escaped_desc = new_description.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    pattern = rf'(Name:\s*"{tool_name}",\s*Description:\s*)"([^"]*(?:\\.[^"]*)*)"'
    replacement = rf'\1"{escaped_desc}"'
    new_content, count = re.subn(pattern, replacement, content, count=1, flags=re.DOTALL)
    if count == 0:
        raise ValueError(f"Tool '{tool_name}' not found in provider.go")
    return new_content


def load_patch_data(bundle: CliBundle) -> CliPatchData:
    """Load current patchable data from the CLI bundle."""
    provider_content = bundle.read_file(PROVIDER_GO_PATH)
    claude_md_content = bundle.read_file(CLAUDE_MD_PATH)

    return CliPatchData(
        template_claude_md=claude_md_content,
        invoke_cli_description=_extract_tool_description(provider_content, "invoke_databricks_cli"),
        discover_description=_extract_tool_description(provider_content, "databricks_discover"),
        configure_auth_description=_extract_tool_description(provider_content, "databricks_configure_auth"),
    )


def apply_patch(bundle: CliBundle, patch_data: CliPatchData) -> None:
    """Apply patch data to the CLI bundle files."""
    if patch_data.template_claude_md is not None:
        bundle.write_file(CLAUDE_MD_PATH, patch_data.template_claude_md)

    tool_patches = [
        ("invoke_databricks_cli", patch_data.invoke_cli_description),
        ("databricks_discover", patch_data.discover_description),
        ("databricks_configure_auth", patch_data.configure_auth_description),
    ]

    patches_to_apply = [(name, desc) for name, desc in tool_patches if desc is not None]
    if not patches_to_apply:
        return

    provider_content = bundle.read_file(PROVIDER_GO_PATH)
    for tool_name, description in patches_to_apply:
        provider_content = _patch_tool_description(provider_content, tool_name, description)
    bundle.write_file(PROVIDER_GO_PATH, provider_content)

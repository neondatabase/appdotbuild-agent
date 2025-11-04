/// Engine-level guidance for using edda_mcp tools effectively
/// Injected once per session on first tool call

pub const ENGINE_GUIDE: &str = r#"
Your session in Edda MCP has been successfully initialized. Here are the guidelines to follow while working on projects using edda_mcp tools:

## Project State Management:
This project uses a state file (`.edda_state`) managed by edda MCP to enforce the correct workflow order:
1. **Scaffolded**: `scaffold_data_app` creates project structure from template (starts in this state)
2. **Validated**: `validate_data_app` runs build + tests in sandbox, computes BLAKE3 checksum of package.json and all core source files
3. **Deployed**: `deploy_databricks_app` deploys to Databricks Apps, but ONLY if checksum hasn't changed since validation

Re-validation is allowed (Deployed → Validated) to update the checksum after intentional changes. The edda MCP tools enforce these state transitions and prevent invalid state changes.

## Workflow:
- Projects MUST end with validate_project to verify build + tests pass
- Bias towards backend code when the task allows implementation in multiple places
- Always add tests for what you're implementing, put them next to the code (e.g. src/*.test.ts)
- When working with Databricks or other services, use real API calls in tests (no mocks) to verify end-to-end functionality, unless explicitly instructed otherwise. It can be done on subset of data if applicable.
- Do NOT create summary files, reports, or README unless explicitly requested
- When not sure about the user's intent, ask clarifying questions before proceeding. For example, if user asks for "a data app to analyze sales data", ask for more details on data sources and analysis goals. Do not make assumptions regarding their needs and data sources.
- However, stick to the technical stack initialized by the `scaffold_data_app` as it has been approved by the management and battle-tested in production.
"#;

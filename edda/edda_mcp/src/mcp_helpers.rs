use rmcp::model::{Implementation, ProtocolVersion, ServerCapabilities, ServerInfo};

/// Helper to create generic ServerInfo for internal providers.
/// These are only used internally by CombinedProvider for routing.
/// Only CombinedProvider's ServerInfo is exposed via MCP.
pub fn internal_server_info() -> ServerInfo {
    ServerInfo {
        protocol_version: ProtocolVersion::V_2024_11_05,
        capabilities: ServerCapabilities::builder().enable_tools().build(),
        server_info: Implementation {
            name: env!("CARGO_PKG_NAME").to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            title: None,
            website_url: None,
            icons: None,
        },
        instructions: None,
    }
}

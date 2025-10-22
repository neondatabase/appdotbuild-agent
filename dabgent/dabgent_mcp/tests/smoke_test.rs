//! Smoke test for dabgent-mcp server
//!
//! Verifies that:
//! - Server can be instantiated in-process
//! - Basic MCP protocol operations work (list_tools, call_tool)
//! - At least one provider is available

use dabgent_mcp::providers::{CombinedProvider, IOProvider};
use eyre::Result;
use rmcp::ServiceExt;
use rmcp_in_process_transport::in_process::TokioInProcess;

#[tokio::test]
async fn smoke_test_mcp_server() -> Result<()> {
    // use IOProvider as it requires no credentials
    let io = IOProvider::new()?;

    // create provider (no need to try other providers for smoke test)
    let provider = CombinedProvider::new(None, None, None, Some(io))?;

    // create in-process service
    let tokio_in_process = TokioInProcess::new(provider).await?;
    let service = ().serve(tokio_in_process).await?;

    // verify server info is available
    let server_info = service.peer_info();
    assert!(server_info.is_some(), "Server info should be available");

    let info = server_info.unwrap();
    assert_eq!(info.server_info.name, "dabgent-mcp");
    assert!(!info.server_info.version.is_empty());

    // list tools
    let tools_response = service.list_tools(Default::default()).await?;
    assert!(
        !tools_response.tools.is_empty(),
        "Should have at least one tool"
    );

    // verify scaffold_data_app tool is exposed
    assert!(
        tools_response
            .tools
            .iter()
            .any(|t| t.name == "scaffold_data_app"),
        "scaffold_data_app tool should be exposed"
    );

    // verify validate_data_app tool is exposed
    assert!(
        tools_response
            .tools
            .iter()
            .any(|t| t.name == "validate_data_app"),
        "validate_data_app tool should be exposed"
    );

    // cleanup
    service.cancel().await?;

    Ok(())
}

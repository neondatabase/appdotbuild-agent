pub mod databricks;
pub mod deployment;
#[cfg(feature = "google-sheets")]
pub mod google_sheets;

// ============================================================================
// Shared Display Trait
// ============================================================================

pub trait ToolResultDisplay {
    fn display(&self) -> String;
}

pub use databricks::{
    ColumnMetadata, DatabricksDescribeTableArgs, DatabricksExecuteQueryArgs,
    DatabricksListCatalogsArgs, DatabricksListSchemasArgs, DatabricksListTablesArgs,
    DatabricksRestClient, DescribeTableRequest, ExecuteSqlRequest, ExecuteSqlResult,
    ListCatalogsResult, ListSchemasRequest, ListSchemasResult, ListTablesRequest,
    ListTablesResult, TableDetails, TableInfo,
};
#[cfg(feature = "google-sheets")]
pub use google_sheets::{
    FetchSpreadsheetDataRequest, GetSpreadsheetMetadataRequest, GoogleSheetsClient,
    ReadRangeRequest, ReadRangeResult, SheetData, SheetMetadata, SpreadsheetData,
    SpreadsheetMetadata,
};
pub use deployment::{AppInfo, create_app, deploy_app, get_app_info, sync_workspace};

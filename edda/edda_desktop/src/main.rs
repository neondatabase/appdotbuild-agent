mod mcp_client;

use eframe::egui;
use mcp_client::{McpClient, Tool};
use std::sync::Arc;
use tracing_subscriber::{fmt, EnvFilter};

struct EddaDesktopApp {
    runtime: tokio::runtime::Runtime,
    client: Option<Arc<McpClient>>,
    tools: Vec<Tool>,
    status: String,
    error_message: Option<String>,
    search_query: String,
}

impl Default for EddaDesktopApp {
    fn default() -> Self {
        Self {
            runtime: tokio::runtime::Runtime::new().unwrap(),
            client: None,
            tools: Vec::new(),
            status: "Not connected".to_string(),
            error_message: None,
            search_query: String::new(),
        }
    }
}

impl EddaDesktopApp {
    fn new(_cc: &eframe::CreationContext<'_>) -> Self {
        let mut app = Self::default();
        app.connect_to_mcp();
        app
    }

    fn connect_to_mcp(&mut self) {
        self.status = "Connecting...".to_string();
        self.error_message = None;

        let binary_path = self.get_binary_path();

        match self.runtime.block_on(async {
            let client = McpClient::spawn(&binary_path).await?;
            let tools = client.list_tools().await?;
            Ok::<_, anyhow::Error>((client, tools))
        }) {
            Ok((client, tools)) => {
                self.client = Some(Arc::new(client));
                self.tools = tools;
                self.status = format!("Connected - {} tools available", self.tools.len());
            }
            Err(e) => {
                self.status = "Connection failed".to_string();
                self.error_message = Some(format!("Error: {:#}", e));
            }
        }
    }

    fn get_binary_path(&self) -> String {
        // in development, use the workspace-built binary
        let workspace_binary = std::env::current_dir()
            .unwrap()
            .join("target/release/edda_mcp");

        if workspace_binary.exists() {
            return workspace_binary.to_string_lossy().to_string();
        }

        // fallback to bundled binary (for production builds)
        "edda_mcp".to_string()
    }
}

impl eframe::App for EddaDesktopApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // configure style for cleaner look
        let mut style = (*ctx.style()).clone();
        style.spacing.item_spacing = egui::vec2(8.0, 8.0);
        style.spacing.window_margin = egui::Margin::same(16.0);
        ctx.set_style(style);

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.vertical(|ui| {
                // header
                ui.add_space(8.0);
                ui.heading(egui::RichText::new("Edda MCP Desktop").size(24.0));
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(8.0);

                // status bar with better styling
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("Status:").strong());

                    let status_color = if self.error_message.is_some() {
                        egui::Color32::from_rgb(220, 53, 69)
                    } else if self.client.is_some() {
                        egui::Color32::from_rgb(40, 167, 69)
                    } else {
                        egui::Color32::GRAY
                    };

                    ui.colored_label(status_color, &self.status);

                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui.button(egui::RichText::new("🔄 Reconnect").size(14.0)).clicked() {
                            self.connect_to_mcp();
                        }
                    });
                });

                ui.add_space(8.0);

                if let Some(error) = &self.error_message {
                    ui.colored_label(egui::Color32::from_rgb(220, 53, 69), error);
                    ui.add_space(8.0);
                }

                ui.separator();
                ui.add_space(8.0);

                // tools section
                if self.tools.is_empty() {
                    ui.vertical_centered(|ui| {
                        ui.add_space(40.0);
                        ui.label(egui::RichText::new("No tools available").size(16.0).color(egui::Color32::GRAY));
                    });
                } else {
                    // search bar
                    ui.horizontal(|ui| {
                        ui.label(egui::RichText::new("🔍").size(16.0));
                        ui.add(
                            egui::TextEdit::singleline(&mut self.search_query)
                                .hint_text("Search tools...")
                                .desired_width(300.0)
                        );
                        if !self.search_query.is_empty() && ui.button("✕").clicked() {
                            self.search_query.clear();
                        }
                    });

                    ui.add_space(8.0);

                    // filter tools based on search
                    let filtered_tools: Vec<_> = self.tools.iter()
                        .filter(|tool| {
                            if self.search_query.is_empty() {
                                true
                            } else {
                                let query = self.search_query.to_lowercase();
                                tool.name.to_lowercase().contains(&query) ||
                                tool.description.as_ref()
                                    .map(|d| d.to_lowercase().contains(&query))
                                    .unwrap_or(false)
                            }
                        })
                        .collect();

                    ui.label(egui::RichText::new(
                        format!("Tools ({}/{})", filtered_tools.len(), self.tools.len())
                    ).strong().size(18.0));

                    ui.add_space(8.0);

                    egui::ScrollArea::vertical()
                        .auto_shrink([false; 2])
                        .show(ui, |ui| {
                            for tool in filtered_tools {
                                egui::Frame::group(ui.style())
                                    .fill(egui::Color32::from_gray(245))
                                    .stroke(egui::Stroke::new(1.0, egui::Color32::from_gray(220)))
                                    .inner_margin(egui::Margin::same(12.0))
                                    .show(ui, |ui| {
                                        ui.label(egui::RichText::new(&tool.name).strong().size(16.0));

                                        if let Some(desc) = &tool.description {
                                            ui.add_space(4.0);
                                            ui.label(egui::RichText::new(desc).size(13.0).color(egui::Color32::DARK_GRAY));
                                        }

                                        ui.add_space(4.0);

                                        egui::CollapsingHeader::new("View Schema")
                                            .id_salt(&tool.name)
                                            .show(ui, |ui| {
                                                let schema_str = serde_json::to_string_pretty(&tool.input_schema)
                                                    .unwrap_or_else(|_| "Invalid schema".to_string());
                                                egui::ScrollArea::vertical()
                                                    .max_height(200.0)
                                                    .show(ui, |ui| {
                                                        ui.code(&schema_str);
                                                    });
                                            });
                                    });

                                ui.add_space(8.0);
                            }
                        });
                }
            });
        });
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        // client will be dropped and cleaned up automatically
        self.client = None;
    }
}

fn main() -> eframe::Result<()> {
    // initialize logging - suppress egui warnings
    fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("edda_desktop=info,egui=warn"))
        )
        .init();

    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([800.0, 600.0])
            .with_title("Edda MCP Desktop"),
        ..Default::default()
    };

    eframe::run_native(
        "Edda MCP Desktop",
        options,
        Box::new(|cc| Ok(Box::new(EddaDesktopApp::new(cc)))),
    )
}

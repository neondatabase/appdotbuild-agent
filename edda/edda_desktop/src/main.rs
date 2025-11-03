mod agent;
mod mcp_client;

use agent::Agent;
use eframe::egui;
use mcp_client::{McpClient, Tool};
use rig::message::{AssistantContent, Message};
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing_subscriber::{fmt, EnvFilter};

enum AgentStatus {
    Idle,
    Running,
    Completed,
    Error(String),
}

#[derive(PartialEq)]
enum Tab {
    Agent,
    Tools,
}

struct EddaDesktopApp {
    runtime: tokio::runtime::Runtime,
    client: Option<Arc<McpClient>>,
    agent: Option<Agent>,
    tools: Vec<Tool>,
    status: String,
    error_message: Option<String>,
    current_tab: Tab,
    // agent UI state
    user_prompt: String,
    agent_status: AgentStatus,
    conversation: Vec<Message>,
    agent_rx: Option<mpsc::UnboundedReceiver<Result<Vec<Message>, String>>>,
}

impl Default for EddaDesktopApp {
    fn default() -> Self {
        Self {
            runtime: tokio::runtime::Runtime::new().unwrap(),
            client: None,
            agent: None,
            tools: Vec::new(),
            status: "Not connected".to_string(),
            error_message: None,
            current_tab: Tab::Agent,
            user_prompt: String::new(),
            agent_status: AgentStatus::Idle,
            conversation: Vec::new(),
            agent_rx: None,
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
                let client_arc = Arc::new(client);
                let tool_defs = tools.iter().map(|t| t.to_rig_definition()).collect();

                // initialize agent
                match Agent::new(client_arc.clone(), tool_defs) {
                    Ok(agent) => {
                        self.agent = Some(agent);
                        self.client = Some(client_arc);
                        self.tools = tools;
                        self.status = format!("Connected - {} tools available", self.tools.len());
                    }
                    Err(e) => {
                        self.status = "Agent initialization failed".to_string();
                        self.error_message = Some(format!("Error: {:#}", e));
                    }
                }
            }
            Err(e) => {
                self.status = "Connection failed".to_string();
                self.error_message = Some(format!("Error: {:#}", e));
            }
        }
    }

    fn get_binary_path(&self) -> String {
        // extract embedded binary to temp location
        const EMBEDDED_BINARY: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/edda_mcp"));

        let temp_dir = std::env::temp_dir();
        let binary_path = temp_dir.join("edda_mcp");

        // write embedded binary if it doesn't exist or is outdated
        if !binary_path.exists() || self.is_binary_outdated(&binary_path) {
            std::fs::write(&binary_path, EMBEDDED_BINARY)
                .expect("Failed to write embedded binary");

            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let mut perms = std::fs::metadata(&binary_path)
                    .expect("Failed to get binary metadata")
                    .permissions();
                perms.set_mode(0o755);
                std::fs::set_permissions(&binary_path, perms)
                    .expect("Failed to set binary permissions");
            }
        }

        binary_path.to_string_lossy().to_string()
    }

    fn is_binary_outdated(&self, path: &std::path::Path) -> bool {
        const EMBEDDED_BINARY: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/edda_mcp"));

        if let Ok(existing) = std::fs::read(path) {
            existing != EMBEDDED_BINARY
        } else {
            true
        }
    }

    fn run_agent(&mut self) {
        if self.agent.is_none() {
            self.agent_status = AgentStatus::Error("Agent not initialized".to_string());
            return;
        }

        if self.user_prompt.trim().is_empty() {
            return;
        }

        let agent = self.agent.as_ref().unwrap().clone();
        let prompt = self.user_prompt.clone();

        self.agent_status = AgentStatus::Running;
        self.conversation.clear();

        let (final_tx, final_rx) = mpsc::unbounded_channel();
        let (progress_tx, mut progress_rx) = mpsc::unbounded_channel();
        self.agent_rx = Some(final_rx);

        // spawn main agent task
        self.runtime.spawn(async move {
            // forward progress updates in the same task
            let progress_final_tx = final_tx.clone();
            let forward_handle = tokio::spawn(async move {
                while let Some(messages) = progress_rx.recv().await {
                    // send progress as Ok result
                    let _ = progress_final_tx.send(Ok(messages));
                }
            });

            // run agent
            let result = agent.run(prompt, Some(progress_tx)).await;

            // wait for progress forwarding to finish (progress_tx is dropped, so progress_rx will close)
            let _ = forward_handle.await;

            // send final result
            let _ = final_tx.send(result.map_err(|e| format!("{:#}", e)));
        });
    }

    fn check_agent_completion(&mut self) {
        if let Some(rx) = &mut self.agent_rx {
            // drain all available messages (could be multiple progress updates)
            let mut final_result = None;

            loop {
                match rx.try_recv() {
                    Ok(result) => {
                        match &result {
                            Ok(messages) => {
                                // update conversation with latest progress
                                self.conversation = messages.clone();
                            }
                            Err(_) => {
                                // this is the final error message
                                final_result = Some(result);
                                break;
                            }
                        }
                    }
                    Err(mpsc::error::TryRecvError::Empty) => {
                        // no more messages available right now
                        break;
                    }
                    Err(mpsc::error::TryRecvError::Disconnected) => {
                        // channel closed, mark as completed
                        self.agent_status = AgentStatus::Completed;
                        self.agent_rx = None;
                        break;
                    }
                }
            }

            // handle final error if any
            if let Some(Err(error)) = final_result {
                self.agent_status = AgentStatus::Error(error);
                self.agent_rx = None;
            }
        }
    }
}

impl eframe::App for EddaDesktopApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // check for agent completion
        self.check_agent_completion();

        // request repaint if agent is running
        if matches!(self.agent_status, AgentStatus::Running) {
            ctx.request_repaint();
        }

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

                // tabs for agent and tools
                egui::TopBottomPanel::top("tabs").show_inside(ui, |ui| {
                    ui.horizontal(|ui| {
                        ui.selectable_value(&mut self.current_tab, Tab::Agent, "🤖 Agent");
                        ui.selectable_value(&mut self.current_tab, Tab::Tools, "🔧 Tools");
                    });
                });

                ui.add_space(8.0);

                // show content based on tab
                match self.current_tab {
                    Tab::Agent => self.render_agent_tab(ui),
                    Tab::Tools => self.render_tools_tab(ui),
                }
            });
        });
    }

}

impl EddaDesktopApp {
    fn render_agent_tab(&mut self, ui: &mut egui::Ui) {
        if self.agent.is_none() {
            ui.vertical_centered(|ui| {
                ui.add_space(40.0);
                ui.label(
                    egui::RichText::new("Agent not available - connect to MCP server first")
                        .size(16.0)
                        .color(egui::Color32::GRAY),
                );
            });
            return;
        }

        // input section
        ui.horizontal(|ui| {
            ui.label(egui::RichText::new("Prompt:").strong());
            let text_edit = egui::TextEdit::multiline(&mut self.user_prompt)
                .hint_text("Enter your prompt here...")
                .desired_width(f32::INFINITY)
                .desired_rows(3);
            ui.add(text_edit);
        });

        ui.add_space(8.0);

        ui.horizontal(|ui| {
            let can_run = matches!(self.agent_status, AgentStatus::Idle | AgentStatus::Completed | AgentStatus::Error(_))
                && !self.user_prompt.trim().is_empty();

            if ui
                .add_enabled(can_run, egui::Button::new("▶ Run Agent"))
                .clicked()
            {
                self.run_agent();
            }

            // show status
            match &self.agent_status {
                AgentStatus::Idle => {
                    ui.colored_label(egui::Color32::GRAY, "Ready");
                }
                AgentStatus::Running => {
                    ui.colored_label(egui::Color32::from_rgb(255, 165, 0), "Running...");
                    ui.spinner();
                }
                AgentStatus::Completed => {
                    ui.colored_label(egui::Color32::from_rgb(40, 167, 69), "Completed");
                }
                AgentStatus::Error(err) => {
                    ui.colored_label(egui::Color32::from_rgb(220, 53, 69), format!("Error: {}", err));
                }
            }
        });

        ui.add_space(8.0);
        ui.separator();
        ui.add_space(8.0);

        // conversation view
        ui.label(egui::RichText::new("Conversation").strong().size(18.0));
        ui.add_space(8.0);

        egui::ScrollArea::vertical()
            .auto_shrink([false; 2])
            .show(ui, |ui| {
                for message in &self.conversation {
                    self.render_message(ui, message);
                }
            });
    }

    fn render_message(&self, ui: &mut egui::Ui, message: &Message) {
        use rig::message::{Text, ToolResultContent, UserContent};
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};

        // helper to create unique IDs based on content
        let make_id = |prefix: &str, content: &str| -> egui::Id {
            let mut hasher = DefaultHasher::new();
            prefix.hash(&mut hasher);
            content.hash(&mut hasher);
            egui::Id::new(hasher.finish())
        };

        match message {
            Message::User { content } => {
                egui::Frame::none()
                    .fill(egui::Color32::from_rgb(230, 240, 255))
                    .inner_margin(egui::Margin::same(12.0))
                    .rounding(egui::Rounding::same(8.0))
                    .show(ui, |ui| {
                        ui.label(egui::RichText::new("👤 User").strong());
                        ui.add_space(4.0);
                        for (idx, item) in content.iter().enumerate() {
                            match item {
                                UserContent::Text(Text { text }) => {
                                    ui.label(text);
                                }
                                UserContent::ToolResult(result) => {
                                    let header_id = make_id("user_tool_result", &format!("{}_{}", result.id, idx));
                                    egui::CollapsingHeader::new(format!("🔨 Tool Result: {}", result.id))
                                        .id_salt(header_id)
                                        .default_open(false)
                                        .show(ui, |ui| {
                                            for content in result.content.iter() {
                                                match content {
                                                    ToolResultContent::Text(Text { text }) => {
                                                        egui::ScrollArea::vertical().max_height(200.0).show(ui, |ui| {
                                                            ui.code(text);
                                                        });
                                                    }
                                                    ToolResultContent::Image(_) => {
                                                        ui.label("[Image]");
                                                    }
                                                }
                                            }
                                        });
                                }
                                _ => {
                                    ui.label("[Unsupported content type]");
                                }
                            }
                        }
                    });
                ui.add_space(8.0);
            }
            Message::Assistant { content, .. } => {
                let text_count = content.iter().filter(|c| matches!(c, AssistantContent::Text(_))).count();
                let tool_count = content.iter().filter(|c| matches!(c, AssistantContent::ToolCall(_))).count();
                let reasoning_count = content.iter().filter(|c| matches!(c, AssistantContent::Reasoning(_))).count();

                egui::Frame::none()
                    .fill(egui::Color32::from_rgb(240, 255, 240))
                    .inner_margin(egui::Margin::same(12.0))
                    .rounding(egui::Rounding::same(8.0))
                    .show(ui, |ui| {
                        ui.horizontal(|ui| {
                            ui.label(egui::RichText::new("🤖 Assistant").strong());
                            ui.label(egui::RichText::new(format!("(text: {}, tools: {}, reasoning: {})", text_count, tool_count, reasoning_count)).weak().small());
                        });
                        ui.add_space(4.0);
                        for (idx, item) in content.iter().enumerate() {
                            match item {
                                AssistantContent::Text(Text { text }) => {
                                    ui.label(text);
                                }
                                AssistantContent::ToolCall(call) => {
                                    let header_id = make_id("assistant_tool_call", &format!("{}_{}", call.id, idx));
                                    ui.add_space(4.0);
                                    egui::Frame::none()
                                        .fill(egui::Color32::from_rgb(255, 250, 230))
                                        .inner_margin(egui::Margin::same(8.0))
                                        .rounding(egui::Rounding::same(4.0))
                                        .show(ui, |ui| {
                                            egui::CollapsingHeader::new(format!("🔧 Tool Call: {}", call.function.name))
                                                .id_salt(header_id)
                                                .default_open(true)
                                                .show(ui, |ui| {
                                                    ui.label(egui::RichText::new("Arguments:").strong().small());
                                                    ui.code(serde_json::to_string_pretty(&call.function.arguments).unwrap_or_default());
                                                });
                                        });
                                    ui.add_space(4.0);
                                }
                                AssistantContent::Reasoning(reasoning) => {
                                    let default_id = "reasoning".to_string();
                                    let reasoning_id = reasoning.id.as_ref().unwrap_or(&default_id);
                                    let header_id = make_id("assistant_reasoning", &format!("{}_{}", reasoning_id, idx));
                                    egui::CollapsingHeader::new("💭 Reasoning")
                                        .id_salt(header_id)
                                        .default_open(true)
                                        .show(ui, |ui| {
                                            for r in &reasoning.reasoning {
                                                ui.label(r);
                                            }
                                        });
                                }
                            }
                        }
                    });
                ui.add_space(8.0);
            }
        }
    }

    fn render_tools_tab(&mut self, ui: &mut egui::Ui) {
        // tools section
        if self.tools.is_empty() {
            ui.vertical_centered(|ui| {
                ui.add_space(40.0);
                ui.label(egui::RichText::new("No tools available").size(16.0).color(egui::Color32::GRAY));
            });
            return;
        }

        // search bar - using a different variable to avoid conflicts with tab selection
        let mut tool_search = String::new();
        ui.horizontal(|ui| {
            ui.label(egui::RichText::new("🔍").size(16.0));
            ui.add(
                egui::TextEdit::singleline(&mut tool_search)
                    .hint_text("Search tools...")
                    .desired_width(300.0)
            );
        });

        ui.add_space(8.0);

        // filter tools based on search
        let filtered_tools: Vec<_> = self.tools.iter()
            .filter(|tool| {
                if tool_search.is_empty() {
                    true
                } else {
                    let query = tool_search.to_lowercase();
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

    #[allow(dead_code)]
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

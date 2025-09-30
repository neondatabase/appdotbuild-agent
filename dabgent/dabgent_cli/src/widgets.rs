use dabgent_agent::event::Event as AgentEvent;
use dabgent_agent::llm::CompletionResponse;
use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::{Color, Style, Stylize},
    text::{Line, Span, Text},
    widgets::{Block, List, ListItem, ListState, StatefulWidget, Widget},
};
use rig::completion::message::{
    AssistantContent, ToolCall, ToolResult, ToolResultContent, UserContent,
};

pub struct EventList<'a> {
    events: &'a [AgentEvent],
}

impl<'a> EventList<'a> {
    pub fn new(events: &'a [AgentEvent]) -> Self {
        Self { events }
    }
}

impl Widget for EventList<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let mut state = ListState::default(); // move to parent state

        let items: Vec<ListItem> = self
            .events
            .iter()
            .map(|event| ListItem::new(event_as_text(event)))
            .collect();

        let list = List::new(items)
            .block(Block::default().title("Event List"))
            .highlight_style(Style::default().fg(Color::Yellow))
            .highlight_symbol(">> ");

        StatefulWidget::render(list, area, buf, &mut state);
    }
}

pub fn event_as_text(event: &AgentEvent) -> Text<'_> {
    match event {
        AgentEvent::LLMConfig {
            model,
            temperature,
            max_tokens,
            preamble,
            tools,
            recipient,
            ..
        } => render_llm_config(model, *temperature, *max_tokens, preamble, tools, recipient),
        AgentEvent::AgentMessage { response, .. } => render_agent_message(response),
        AgentEvent::UserMessage(content) => render_user_message(content),
        AgentEvent::ArtifactsCollected(artifacts) => render_artifacts_collected(artifacts),
        AgentEvent::TaskCompleted { .. } => Text::raw("Task completed"),
        AgentEvent::SeedSandboxFromTemplate { .. } => Text::raw("Sandbox seeded from template"),
        AgentEvent::SandboxSeeded { .. } => Text::raw("Sandbox seeded"),
        AgentEvent::PipelineShutdown => Text::raw("Pipeline shutdown"),
        AgentEvent::ToolResult(_) => Text::raw("Tool result"),
        AgentEvent::PlanCreated { tasks } => render_plan_created(tasks),
        AgentEvent::PlanUpdated { tasks } => render_plan_updated(tasks),
        AgentEvent::DelegateWork { agent_type, .. } => Text::raw(format!("Delegating work to: {}", agent_type)),
        AgentEvent::WorkComplete { agent_type, .. } => Text::raw(format!("Work completed by: {}", agent_type)),
    }
}

pub fn render_artifacts_collected(
    artifacts: &std::collections::HashMap<String, String>,
) -> Text<'_> {
    Text::from(format!("Collected {} artifacts", artifacts.len()))
}

pub fn render_plan_created(tasks: &[String]) -> Text<'_> {
    let mut lines = vec![Line::from("Plan created with tasks:")];
    for (i, task) in tasks.iter().enumerate() {
        lines.push(Line::from(format!("  {}. {}", i + 1, task)));
    }
    Text::from(lines)
}

pub fn render_plan_updated(tasks: &[String]) -> Text<'_> {
    let mut lines = vec![Line::from("Plan updated with tasks:")];
    for (i, task) in tasks.iter().enumerate() {
        lines.push(Line::from(format!("  {}. {}", i + 1, task)));
    }
    Text::from(lines)
}

pub fn render_llm_config<'a>(
    model: &'a str,
    temperature: f64,
    max_tokens: u64,
    preamble: &'a Option<String>,
    tools: &'a Option<Vec<rig::completion::ToolDefinition>>,
    recipient: &'a Option<String>,
) -> Text<'a> {
    let mut lines = Vec::new();
    lines.push(Line::from(vec![
        Span::styled("Configured model", Style::new().bold()),
        Span::raw(format!(": {model}")),
    ]));
    lines.push(Line::from(format!(
        "temperature: {temperature}, max_tokens: {max_tokens}"
    )));
    if let Some(preamble) = preamble {
        lines.push(Line::from(vec![
            Span::styled("preamble", Style::new().italic()),
            Span::raw(": "),
            Span::raw(preamble.clone()),
        ]));
    }
    if let Some(tools) = tools {
        let names = tools
            .iter()
            .map(|tool| tool.name.clone())
            .collect::<Vec<_>>();
        lines.push(Line::from(vec![
            Span::styled("tools", Style::new().italic()),
            Span::raw(": "),
            Span::raw(names.join(", ")),
        ]));
    }
    if let Some(recipient) = recipient {
        lines.push(Line::from(vec![
            Span::styled("recipient", Style::new().italic()),
            Span::raw(": "),
            Span::raw(recipient.clone()),
        ]));
    }
    Text::from(lines)
}

pub fn render_agent_message(completion: &CompletionResponse) -> Text<'_> {
    let mut lines = Vec::new();
    for item in completion.choice.iter() {
        match item {
            AssistantContent::Text(text) => {
                for line in text.text.lines() {
                    lines.push(Line::from(line.to_owned()));
                }
            }
            AssistantContent::Reasoning(reasoning) => {
                lines.push(Line::from("[reasoning]"));
                for line in reasoning.reasoning.iter() {
                    lines.push(Line::from(line.to_owned()));
                }
            }
            AssistantContent::ToolCall(tool_call) => {
                lines.append(&mut tool_call_lines(tool_call));
            }
        }
    }
    Text::from(lines)
}

pub fn render_user_message(response: &rig::OneOrMany<UserContent>) -> Text<'_> {
    let mut lines = Vec::new();
    for item in response.iter() {
        match item {
            UserContent::Text(text) => {
                for line in text.text.lines() {
                    lines.push(Line::from(line.to_owned()));
                }
            }
            UserContent::ToolResult(tool_result) => {
                lines.append(&mut tool_result_lines(tool_result));
            }
            UserContent::Image(_) => lines.push(Line::from("[image]")),
            UserContent::Audio(_) => lines.push(Line::from("[audio]")),
            UserContent::Video(_) => lines.push(Line::from("[video]")),
            UserContent::Document(_) => lines.push(Line::from("[document]")),
        }
    }
    Text::from(lines)
}

pub fn tool_call_lines(value: &ToolCall) -> Vec<Line<'_>> {
    let args = serde_json::to_string_pretty(&value.function.arguments).unwrap();
    let mut lines = vec![Line::from(vec![
        Span::styled(value.function.name.clone(), Style::new().bold()),
        Span::raw(" "),
        Span::styled(format!("[{}]", value.id), Style::new().gray()),
    ])];
    for line in args.lines() {
        lines.push(Line::from(line.to_owned()));
    }
    lines
}

pub fn tool_result_lines(value: &ToolResult) -> Vec<Line<'_>> {
    let mut lines = vec![Line::from(vec![Span::styled(
        format!("[{}]", value.id),
        Style::new().gray(),
    )])];
    for item in value.content.iter() {
        match item {
            ToolResultContent::Text(text) => {
                match serde_json::from_str::<serde_json::Value>(&text.text) {
                    Ok(json_value) => {
                        for line in serde_json::to_string_pretty(&json_value).unwrap().lines() {
                            lines.push(Line::from(line.to_owned()));
                        }
                    }
                    Err(_) => lines.push(Line::from(text.text.clone())),
                }
            }
            ToolResultContent::Image(..) => {
                lines.push(Line::from("[image]"));
            }
        }
    }
    lines
}

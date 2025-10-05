use dabgent_agent::llm::CompletionResponse;
use dabgent_agent::processor::agent::Event;
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

pub struct EventList<'a, T> {
    events: &'a [Event<T>],
}

impl<'a, T> EventList<'a, T> {
    pub fn new(events: &'a [Event<T>]) -> Self {
        Self { events }
    }
}

impl<T> Widget for EventList<'_, T> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let mut state = ListState::default(); // move to parent state

        let items: Vec<ListItem> = self
            .events
            .iter()
            .filter_map(|event| event_as_text(event).map(ListItem::new))
            .collect();

        let list = List::new(items)
            .block(Block::default().title("Event List"))
            .highlight_style(Style::default().fg(Color::Yellow))
            .highlight_symbol(">> ");

        StatefulWidget::render(list, area, buf, &mut state);
    }
}

pub fn event_as_text<T>(event: &Event<T>) -> Option<Text<'_>> {
    match event {
        Event::UserCompletion { content } => Some(render_user_message(&content)),
        Event::AgentCompletion { response } => Some(render_agent_message(response)),
        _ => None,
    }
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

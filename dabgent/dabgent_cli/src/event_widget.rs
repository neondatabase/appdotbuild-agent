use dabgent_agent::thread::Event;
use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Paragraph, Widget},
};

pub struct EventWidget<'a> {
    event: &'a Event,
    expanded: bool,
    selected: bool,
}

impl<'a> EventWidget<'a> {
    pub fn new(event: &'a Event) -> Self {
        Self {
            event,
            expanded: false,
            selected: false,
        }
    }

    pub fn expanded(mut self, expanded: bool) -> Self {
        self.expanded = expanded;
        self
    }

    pub fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    fn render_content(&self) -> Text<'static> {
        match self.event {
            Event::Prompted(prompt) => self.render_prompted(prompt),
            Event::LlmCompleted(response) => self.render_llm_completed(response),
            Event::ToolCompleted(response) => self.render_tool_completed(response),
        }
    }

    fn render_prompted(&self, prompt: &str) -> Text<'static> {
        let mut lines = vec![Line::from(vec![Span::styled(
            "[PROMPT]",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )])];

        if self.expanded {
            for line in prompt.lines() {
                lines.push(Line::from(format!("  {}", line)));
            }
        } else {
            lines.push(Line::from(format!("  {}", truncate_str(prompt, 80))));
        }

        Text::from(lines)
    }

    fn render_llm_completed(
        &self,
        response: &dabgent_agent::llm::CompletionResponse,
    ) -> Text<'static> {
        let mut lines = vec![Line::from(vec![Span::styled(
            "[LLM]",
            Style::default()
                .fg(Color::Green)
                .add_modifier(Modifier::BOLD),
        )])];

        if self.expanded {
            for item in response.choice.iter() {
                match item {
                    rig::message::AssistantContent::Text(text) => {
                        for line in text.text.lines() {
                            lines.push(Line::from(format!("  {}", line)));
                        }
                    }
                    rig::message::AssistantContent::ToolCall(call) => {
                        lines.push(Line::from(vec![
                            Span::raw("  "),
                            Span::styled("🔧 Tool Call: ", Style::default().fg(Color::Cyan)),
                            Span::raw(call.function.name.clone()),
                        ]));
                        if let Ok(pretty) = serde_json::to_string_pretty(&call.function.arguments) {
                            for line in pretty.lines() {
                                lines.push(Line::from(format!("    {}", line)));
                            }
                        }
                    }
                    rig::message::AssistantContent::Reasoning(reasoning) => {
                        lines.push(Line::from(vec![
                            Span::raw("  "),
                            Span::styled("[Reasoning]", Style::default().fg(Color::DarkGray)),
                        ]));
                        for reason_text in &reasoning.reasoning {
                            for line in reason_text.lines() {
                                lines.push(Line::from(format!("    {}", line)));
                            }
                        }
                    }
                }
            }
        } else {
            let summary = self.summarize_llm_response(response);
            lines.push(Line::from(format!("  {}", summary)));
        }

        Text::from(lines)
    }

    fn render_tool_completed(
        &self,
        response: &dabgent_agent::thread::ToolResponse,
    ) -> Text<'static> {
        let mut lines = vec![Line::from(vec![Span::styled(
            "[TOOL]",
            Style::default()
                .fg(Color::Magenta)
                .add_modifier(Modifier::BOLD),
        )])];

        if self.expanded {
            for item in response.content.iter() {
                match item {
                    rig::message::UserContent::Text(text) => {
                        for line in text.text.lines() {
                            lines.push(Line::from(format!("  {}", line)));
                        }
                    }
                    rig::message::UserContent::ToolResult(result) => {
                        lines.push(Line::from(vec![
                            Span::raw("  "),
                            Span::styled(
                                format!("[Result: {}]", result.id),
                                Style::default().fg(Color::Blue),
                            ),
                        ]));
                        for content in result.content.iter() {
                            match content {
                                rig::message::ToolResultContent::Text(t) => {
                                    for line in t.text.lines() {
                                        lines.push(Line::from(format!("    {}", line)));
                                    }
                                }
                                _ => continue,
                            }
                        }
                    }
                    _ => continue,
                }
            }
        } else {
            let summary = self.summarize_tool_response(response);
            lines.push(Line::from(format!("  {}", summary)));
        }

        Text::from(lines)
    }

    fn summarize_llm_response(&self, response: &dabgent_agent::llm::CompletionResponse) -> String {
        let mut parts = Vec::new();

        for item in response.choice.iter() {
            match item {
                rig::message::AssistantContent::Text(text) => {
                    parts.push(truncate_str(&text.text, 60));
                }
                rig::message::AssistantContent::ToolCall(call) => {
                    parts.push(format!("🔧 {}", call.function.name));
                }
                rig::message::AssistantContent::Reasoning(_) => {
                    parts.push("[reasoning]".to_string());
                }
            }
        }

        parts.join(" | ")
    }

    fn summarize_tool_response(&self, response: &dabgent_agent::thread::ToolResponse) -> String {
        let mut parts = Vec::new();

        for item in response.content.iter() {
            match item {
                rig::message::UserContent::Text(text) => {
                    parts.push(truncate_str(&text.text, 60));
                }
                rig::message::UserContent::ToolResult(result) => {
                    let content = result
                        .content
                        .iter()
                        .filter_map(|c| match c {
                            rig::message::ToolResultContent::Text(t) => {
                                Some(truncate_str(&t.text, 40))
                            }
                            _ => None,
                        })
                        .collect::<Vec<_>>()
                        .join(", ");
                    parts.push(format!("[{}] {}", result.id, content));
                }
                _ => continue,
            }
        }

        parts.join(" | ")
    }
}

impl Widget for EventWidget<'_> {
    fn render(self, area: Rect, buf: &mut Buffer) {
        let content = self.render_content();

        let style = if self.selected {
            Style::default().bg(Color::DarkGray)
        } else {
            Style::default()
        };

        let paragraph = Paragraph::new(content).style(style);
        paragraph.render(area, buf);
    }
}

fn truncate_str(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        s.to_string()
    } else {
        format!("{}...", &s[..max_len.saturating_sub(3)])
    }
}

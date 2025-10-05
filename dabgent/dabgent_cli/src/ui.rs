use crate::App;
use crate::widgets::event_as_text;
use dabgent_agent::processor::agent::Agent;
use dabgent_mq::EventStore;
use ratatui::{
    buffer::Buffer,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Style, Stylize},
    widgets::{Block, Borders, List, ListItem, Paragraph, StatefulWidget, Widget},
};

impl<A: Agent, ES: EventStore> Widget for &mut App<A, ES> {
    fn render(self, area: Rect, buf: &mut Buffer)
    where
        Self: Sized,
    {
        let main_chunks = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(70), Constraint::Percentage(30)])
            .split(area);

        let content_chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(3), Constraint::Length(3)])
            .split(main_chunks[0]);

        self.draw_messages(content_chunks[0], buf);
        self.draw_input(content_chunks[1], buf);
    }
}

impl<A: Agent, ES: EventStore> App<A, ES> {
    fn draw_messages(&mut self, area: Rect, buf: &mut Buffer) {
        let items: Vec<ListItem> = self
            .history
            .iter()
            .filter_map(|event| event_as_text(event).map(ListItem::new))
            .collect();

        let title = if self.auto_scroll {
            "Event List (Auto-scroll ON | Use ↑↓ to navigate)"
        } else {
            "Event List (Auto-scroll OFF | Press End to re-enable)"
        };

        let messages_list = List::new(items)
            .block(Block::default().borders(Borders::ALL).title(title))
            .highlight_style(Style::default().yellow())
            .highlight_symbol(">> ");

        StatefulWidget::render(messages_list, area, buf, &mut self.list_state);
    }

    fn draw_input(&self, area: Rect, buf: &mut Buffer) {
        let input = Paragraph::new(self.input_buffer.as_str())
            .style(Style::default())
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .title("Input (Enter to send)"),
            );

        input.render(area, buf);
    }
}

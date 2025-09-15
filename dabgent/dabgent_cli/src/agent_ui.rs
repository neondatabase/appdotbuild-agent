use crate::event_widget::EventWidget;
use color_eyre::Result;
use crossterm::{
    event::{self, Event as CEvent, KeyCode},
    execute,
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
};
use dabgent_agent::thread::Event;
use dabgent_mq::db::{EventStore, Query, sqlite::SqliteStore};
use ratatui::{
    Frame, Terminal,
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph},
};
use sqlx::SqlitePool;
use std::io;

pub async fn demo() -> Result<()> {
    tracing_subscriber::fmt::init();
    let events = load_demo_events("sqbasic.db").await?;

    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // Run the UI
    let res = run_app(&mut terminal, &events).await;

    // Restore terminal
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;

    if let Err(err) = res {
        eprintln!("Error: {:?}", err);
    }

    Ok(())
}

async fn run_app<B: ratatui::backend::Backend>(
    terminal: &mut Terminal<B>,
    events: &[Event],
) -> Result<()> {
    let mut selected_index = 0;
    let mut expanded_index: Option<usize> = None;

    loop {
        terminal.draw(|f| draw_ui(f, events, selected_index, expanded_index))?;

        if let CEvent::Key(key) = event::read()? {
            match key.code {
                KeyCode::Char('q') | KeyCode::Esc => break,
                KeyCode::Down | KeyCode::Char('j') => {
                    if selected_index < events.len().saturating_sub(1) {
                        selected_index += 1;
                    }
                }
                KeyCode::Up | KeyCode::Char('k') => {
                    if selected_index > 0 {
                        selected_index -= 1;
                    }
                }
                KeyCode::Enter | KeyCode::Char(' ') => {
                    if expanded_index == Some(selected_index) {
                        expanded_index = None;
                    } else {
                        expanded_index = Some(selected_index);
                    }
                }
                _ => {}
            }
        }
    }

    Ok(())
}

fn draw_ui(f: &mut Frame, events: &[Event], selected_index: usize, expanded_index: Option<usize>) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([Constraint::Min(5), Constraint::Length(3)])
        .split(f.area());

    // Draw events list
    draw_events_list(f, chunks[0], events, selected_index, expanded_index);

    // Draw help
    draw_help(f, chunks[1]);
}

fn draw_events_list(
    f: &mut Frame,
    area: Rect,
    events: &[Event],
    selected_index: usize,
    expanded_index: Option<usize>,
) {
    let block = Block::default()
        .title(" Thread Events ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan));

    let inner = block.inner(area);
    f.render_widget(block, area);

    // Calculate visible area and render events
    let mut y_offset = 0;
    let scroll_offset = calculate_scroll_offset(
        selected_index,
        expanded_index,
        events.len(),
        inner.height as usize,
    );

    for (i, event) in events.iter().enumerate().skip(scroll_offset) {
        if y_offset >= inner.height {
            break;
        }

        let is_expanded = expanded_index == Some(i);
        let is_selected = i == selected_index;

        let widget = EventWidget::new(event)
            .expanded(is_expanded)
            .selected(is_selected);

        // Calculate the height this event will take
        let event_height = calculate_event_height(event, is_expanded);

        if y_offset + event_height <= inner.height {
            let event_area = Rect {
                x: inner.x,
                y: inner.y + y_offset,
                width: inner.width,
                height: event_height.min(inner.height - y_offset),
            };

            f.render_widget(widget, event_area);
            y_offset += event_height;
        } else {
            break;
        }
    }
}

fn calculate_event_height(event: &Event, expanded: bool) -> u16 {
    if !expanded {
        2 // Header + one line summary
    } else {
        match event {
            Event::Prompted(prompt) => 1 + prompt.lines().count() as u16,
            Event::LlmCompleted(response) => {
                let mut lines = 1;
                for item in response.choice.iter() {
                    match item {
                        rig::message::AssistantContent::Text(text) => {
                            lines += text.text.lines().count();
                        }
                        rig::message::AssistantContent::ToolCall(call) => {
                            lines += 1;
                            if let Ok(pretty) =
                                serde_json::to_string_pretty(&call.function.arguments)
                            {
                                lines += pretty.lines().count();
                            }
                        }
                        rig::message::AssistantContent::Reasoning(reasoning) => {
                            lines += 1 + reasoning
                                .reasoning
                                .iter()
                                .map(|s| s.lines().count())
                                .sum::<usize>();
                        }
                    }
                }
                lines as u16
            }
            Event::ToolCompleted(response) => {
                let mut lines = 1;
                for item in response.content.iter() {
                    match item {
                        rig::message::UserContent::Text(text) => {
                            lines += text.text.lines().count();
                        }
                        rig::message::UserContent::ToolResult(result) => {
                            lines += 1;
                            for content in result.content.iter() {
                                if let rig::message::ToolResultContent::Text(t) = content {
                                    lines += t.text.lines().count();
                                }
                            }
                        }
                        _ => lines += 1,
                    }
                }
                lines as u16
            }
        }
    }
}

fn calculate_scroll_offset(
    selected_index: usize,
    _expanded_index: Option<usize>,
    total_events: usize,
    visible_height: usize,
) -> usize {
    // Simple scrolling logic - keep selected item visible
    if selected_index < visible_height / 2 {
        0
    } else if selected_index > total_events.saturating_sub(visible_height / 2) {
        total_events.saturating_sub(visible_height)
    } else {
        selected_index.saturating_sub(visible_height / 2)
    }
}

fn draw_help(f: &mut Frame, area: Rect) {
    let help_text = vec![Line::from(vec![
        Span::styled("[q/Esc]", Style::default().fg(Color::Yellow)),
        Span::raw(" Quit  "),
        Span::styled("[↑/k]", Style::default().fg(Color::Yellow)),
        Span::raw(" Up  "),
        Span::styled("[↓/j]", Style::default().fg(Color::Yellow)),
        Span::raw(" Down  "),
        Span::styled("[Enter/Space]", Style::default().fg(Color::Yellow)),
        Span::raw(" Expand/Collapse"),
    ])];

    let paragraph = Paragraph::new(help_text)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(Style::default().fg(Color::DarkGray)),
        )
        .style(Style::default().fg(Color::Gray));

    f.render_widget(paragraph, area);
}

async fn load_demo_events(db_path: &str) -> Result<Vec<Event>> {
    let pool = SqlitePool::connect(db_path).await?;
    let store = SqliteStore::new(pool);
    let query = Query {
        stream_id: "basic".to_owned(),
        event_type: None,
        aggregate_id: Some("thread".to_owned()),
    };
    store.load_events(&query, None).await.map_err(Into::into)
}

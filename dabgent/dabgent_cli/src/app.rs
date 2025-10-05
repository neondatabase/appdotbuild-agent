use crate::events::{AppEvent, CliEvent, EventHandler};
use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use dabgent_agent::processor::agent::{Agent, AgentState, Command, Event};
use dabgent_agent::processor::link::Runtime;
use dabgent_mq::{EventQueue, EventStore, Handler};
use ratatui::widgets::ListState;

pub struct App<A: Agent, ES: EventStore> {
    pub handler: Handler<AgentState<A>, ES>,
    pub aggregate_id: String,
    pub history: Vec<Event<A::AgentEvent>>,
    pub input_buffer: String,
    pub running: bool,
    pub events: EventHandler<A::AgentEvent>,
    pub list_state: ListState,
    pub auto_scroll: bool,
}

impl<A: Agent + 'static, ES: EventQueue + 'static> App<A, ES>
where
    ES: EventStore,
    A::Services: Clone,
{
    pub fn new(
        runtime: &mut Runtime<AgentState<A>, ES>,
        aggregate_id: String,
    ) -> color_eyre::Result<Self> {
        Ok(Self {
            aggregate_id,
            handler: runtime.handler.clone(),
            history: Vec::new(),
            input_buffer: String::new(),
            running: true,
            events: EventHandler::new(runtime),
            list_state: ListState::default(),
            auto_scroll: true,
        })
    }

    pub async fn run(mut self, mut terminal: ratatui::DefaultTerminal) -> color_eyre::Result<()> {
        while self.running {
            terminal.draw(|frame| frame.render_widget(&mut self, frame.area()))?;
            match self.events.next().await? {
                CliEvent::Tick => self.tick(),
                CliEvent::Crossterm(event) => match event {
                    crossterm::event::Event::Key(key_event) => self.handle_key_events(key_event)?,
                    _ => {}
                },
                CliEvent::Agent(event) => {
                    self.history.push(event);
                    if self.auto_scroll && !self.history.is_empty() {
                        self.list_state.select(Some(self.history.len() - 1));
                    }
                }
                CliEvent::App(app_event) => match app_event {
                    AppEvent::Confirm => self.confirm().await?,
                    AppEvent::Erase => self.erase(),
                    AppEvent::Input(input) => self.input(input),
                    AppEvent::Quit => self.quit(),
                },
            }
        }
        Ok(())
    }

    pub fn handle_key_events(&mut self, key: KeyEvent) -> color_eyre::Result<()> {
        match key.code {
            KeyCode::Enter => self.events.send(CliEvent::App(AppEvent::Confirm)),
            KeyCode::Char('c' | 'C') if key.modifiers == KeyModifiers::CONTROL => {
                self.events.send(CliEvent::App(AppEvent::Quit))
            }
            KeyCode::Char(c) => self.events.send(CliEvent::App(AppEvent::Input(c))),
            KeyCode::Backspace => self.events.send(CliEvent::App(AppEvent::Erase)),
            KeyCode::Up => {
                self.auto_scroll = false;
                if let Some(selected) = self.list_state.selected() {
                    if selected > 0 {
                        self.list_state.select(Some(selected - 1));
                    }
                } else if !self.history.is_empty() {
                    self.list_state.select(Some(self.history.len() - 1));
                }
            }
            KeyCode::Down => {
                if let Some(selected) = self.list_state.selected() {
                    if selected < self.history.len() - 1 {
                        self.list_state.select(Some(selected + 1));
                        // Re-enable auto-scroll if we reach the bottom
                        if selected + 1 == self.history.len() - 1 {
                            self.auto_scroll = true;
                        }
                    }
                } else if !self.history.is_empty() {
                    self.list_state.select(Some(0));
                }
            }
            KeyCode::PageUp => {
                self.auto_scroll = false;
                if !self.history.is_empty() {
                    let current = self.list_state.selected().unwrap_or(self.history.len() - 1);
                    let new_pos = current.saturating_sub(10);
                    self.list_state.select(Some(new_pos));
                }
            }
            KeyCode::PageDown => {
                if !self.history.is_empty() {
                    let current = self.list_state.selected().unwrap_or(0);
                    let new_pos = (current + 10).min(self.history.len() - 1);
                    self.list_state.select(Some(new_pos));
                    // Re-enable auto-scroll if we reach the bottom
                    if new_pos == self.history.len() - 1 {
                        self.auto_scroll = true;
                    }
                }
            }
            KeyCode::Home => {
                self.auto_scroll = false;
                if !self.history.is_empty() {
                    self.list_state.select(Some(0));
                }
            }
            KeyCode::End => {
                self.auto_scroll = true;
                if !self.history.is_empty() {
                    self.list_state.select(Some(self.history.len() - 1));
                }
            }
            _ => {}
        }
        Ok(())
    }

    async fn send_message(&mut self) -> color_eyre::Result<()> {
        let content = self.input_buffer.clone();
        let text = rig::message::UserContent::text(content);
        let message = rig::OneOrMany::one(text);
        let command = Command::PutUserMessage { content: message };
        self.handler.execute(&self.aggregate_id, command).await?;
        Ok(())
    }

    pub fn tick(&self) {
        // animations
    }

    pub fn erase(&mut self) {
        self.input_buffer.pop();
    }

    pub fn quit(&mut self) {
        self.running = false;
    }

    pub async fn confirm(&mut self) -> color_eyre::Result<()> {
        if !self.input_buffer.is_empty() {
            self.send_message().await?;
            self.input_buffer.clear();
        }
        Ok(())
    }

    pub fn input(&mut self, input: char) {
        self.input_buffer.push(input);
    }
}

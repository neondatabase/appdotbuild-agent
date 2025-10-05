use color_eyre::eyre::OptionExt;
use crossterm::event::Event as CrosstermEvent;
use dabgent_agent::processor::agent::{Agent, AgentState, Event};
use dabgent_agent::processor::link::Runtime;
use dabgent_mq::{Callback, Envelope, EventQueue};
use std::time::Duration;
use tokio::sync::mpsc;
use tokio_stream::StreamExt;

const TICK_FPS: f64 = 30.0;

#[derive(Debug, Clone)]
pub enum AppEvent {
    Confirm,
    Erase,
    Input(char),
    Quit,
}

#[derive(Debug, Clone)]
pub enum CliEvent<T> {
    Tick,
    Crossterm(CrosstermEvent),
    Agent(Event<T>),
    App(AppEvent),
}

pub struct EventHandler<T> {
    sender: mpsc::UnboundedSender<CliEvent<T>>,
    receiver: mpsc::UnboundedReceiver<CliEvent<T>>,
}

impl<T: Send + 'static> EventHandler<T> {
    pub fn new<A, ES>(runtime: &mut Runtime<AgentState<A>, ES>) -> Self
    where
        A: Agent<AgentEvent = T>,
        ES: EventQueue,
    {
        let (sender, receiver) = mpsc::unbounded_channel();
        let actor = EventTask::new(sender.clone());
        tokio::spawn(async { actor.run().await });
        let forwarder = CliForwarder::new(sender.clone());
        runtime.listener.push_callback(forwarder);
        Self { sender, receiver }
    }

    pub async fn next(&mut self) -> color_eyre::Result<CliEvent<T>> {
        self.receiver
            .recv()
            .await
            .ok_or_eyre("Failed to receive event")
    }

    pub fn send(&self, event: CliEvent<T>) {
        let _ = self.sender.send(event);
    }
}

pub struct EventTask<T> {
    sender: mpsc::UnboundedSender<CliEvent<T>>,
}

impl<T> EventTask<T> {
    pub fn new(sender: mpsc::UnboundedSender<CliEvent<T>>) -> Self {
        Self { sender }
    }

    pub async fn run(self) -> color_eyre::Result<()> {
        let tick_rate = Duration::from_secs_f64(1.0 / TICK_FPS);
        let mut reader = crossterm::event::EventStream::new();
        let mut tick = tokio::time::interval(tick_rate);
        loop {
            let tick_delay = tick.tick();
            tokio::select! {
                _ = self.sender.closed() => {
                    break;
                }
                _ = tick_delay => {
                    self.send(CliEvent::Tick);
                }
                Some(Ok(evt)) = reader.next() => {
                    self.send(CliEvent::Crossterm(evt));
                }
            };
        }
        Ok(())
    }

    fn send(&self, event: CliEvent<T>) {
        let _ = self.sender.send(event);
    }
}

struct CliForwarder<T> {
    sender: mpsc::UnboundedSender<CliEvent<T>>,
}

impl<T> CliForwarder<T> {
    pub fn new(sender: mpsc::UnboundedSender<CliEvent<T>>) -> Self {
        Self { sender }
    }
}

impl<A: Agent> Callback<AgentState<A>> for CliForwarder<A::AgentEvent> {
    async fn process(&mut self, envelope: &Envelope<AgentState<A>>) -> eyre::Result<()> {
        let _ = self.sender.send(CliEvent::Agent(envelope.data.clone()));
        Ok(())
    }
}

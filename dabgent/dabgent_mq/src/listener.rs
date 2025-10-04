use crate::{Aggregate, Envelope, EventStore, Handler};
use eyre::Result;
use std::collections::HashMap;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{Mutex, broadcast, mpsc};

const WAKE_CHANNEL_SIZE: usize = 100;

pub trait Callback<A: Aggregate>: Send {
    fn process(&mut self, event: &Envelope<A>) -> impl Future<Output = Result<()>> + Send;
    fn boxed(self) -> Box<dyn CallbackDyn<A>>
    where
        Self: Sized + 'static,
    {
        Box::new(self)
    }
}

pub trait EventHandler<A: Aggregate, ES: EventStore>: Send {
    fn process(
        &mut self,
        handler: &Handler<A, ES>,
        event: &Envelope<A>,
    ) -> impl Future<Output = Result<()>> + Send;
}

pub trait CallbackDyn<A: Aggregate>: Send {
    fn process<'a>(
        &'a mut self,
        event: &'a Envelope<A>,
    ) -> Pin<Box<dyn Future<Output = Result<()>> + Send + 'a>>;
}

impl<A: Aggregate, T: Callback<A>> CallbackDyn<A> for T {
    fn process<'a>(
        &'a mut self,
        event: &'a Envelope<A>,
    ) -> Pin<Box<dyn Future<Output = Result<()>> + Send + 'a>> {
        Box::pin(self.process(event))
    }
}

#[derive(Clone)]
pub struct Wake {
    aggregate_type: &'static str,
    aggregate_id: String,
    current_sequence: i64,
}

#[derive(Clone)]
pub struct PollingQueue<ES: EventStore> {
    store: ES,
    wake_tx: broadcast::Sender<Wake>,
}

impl<ES: EventStore> EventStore for PollingQueue<ES> {
    async fn commit<A: Aggregate>(
        &self,
        events: Vec<A::Event>,
        metadata: crate::Metadata,
        context: crate::AggregateContext<A>,
    ) -> Result<Vec<Envelope<A>>, crate::db::Error> {
        let wake = Wake {
            aggregate_type: A::TYPE,
            aggregate_id: context.aggregate_id.clone(),
            current_sequence: context.current_sequence,
        };
        let events = self.store.commit(events, metadata, context).await?;
        let _ = self.wake_tx.send(wake);
        Ok(events)
    }

    async fn load_aggregate<A: Aggregate>(
        &self,
        aggregate_id: &str,
    ) -> Result<crate::AggregateContext<A>, crate::db::Error> {
        self.store.load_aggregate(aggregate_id).await
    }

    async fn load_events<A: Aggregate>(
        &self,
        aggregate_id: &str,
    ) -> Result<Vec<Envelope<A>>, crate::db::Error> {
        self.store.load_events(aggregate_id).await
    }

    async fn load_latest_events<A: Aggregate>(
        &self,
        aggregate_id: &str,
        sequence_from: i64,
    ) -> Result<Vec<Envelope<A>>, crate::db::Error> {
        self.store
            .load_latest_events(aggregate_id, sequence_from)
            .await
    }

    async fn load_sequence_nums<A: Aggregate>(
        &self,
    ) -> Result<Vec<(String, i64)>, crate::db::Error> {
        self.store.load_sequence_nums::<A>().await
    }
}

pub trait EventQueue: EventStore {
    fn listener<A: Aggregate + 'static>(&self) -> Listener<A, Self>;
}

impl<ES: EventStore> EventQueue for PollingQueue<ES> {
    fn listener<A: Aggregate + 'static>(&self) -> Listener<A, Self> {
        Listener::new(self.clone(), self.wake_tx.subscribe())
    }
}

impl<ES: EventStore> PollingQueue<ES> {
    pub fn new(store: ES) -> Self {
        let (wake_tx, _) = broadcast::channel(WAKE_CHANNEL_SIZE);
        Self { store, wake_tx }
    }
}

type ArcCallback<A> = Arc<Mutex<dyn CallbackDyn<A>>>;

pub struct Listener<A: Aggregate + 'static, ES: EventStore> {
    store: ES,
    wake_rx: broadcast::Receiver<Wake>,
    callbacks: Vec<ArcCallback<A>>,
    offsets: HashMap<String, i64>,
    poll_interval: Duration,
}

impl<A: Aggregate + 'static, ES: EventStore> Listener<A, ES> {
    pub fn new(store: ES, wake_rx: broadcast::Receiver<Wake>) -> Self {
        Self {
            store,
            wake_rx,
            callbacks: Vec::new(),
            offsets: HashMap::new(),
            poll_interval: Duration::from_secs(1),
        }
    }

    pub fn with_poll_interval(mut self, interval: Duration) -> Self {
        self.poll_interval = interval;
        self
    }

    pub fn push_callback<C: Callback<A> + 'static>(&mut self, callback: C) {
        self.callbacks.push(Arc::new(Mutex::new(callback)));
    }

    pub fn push_handler<H: EventHandler<A, ES> + 'static>(
        &mut self,
        handler: H,
        services: A::Services,
    ) {
        let h = Handler::new(self.store.clone(), services);
        let adapter = CallbackAdapter::new(h, handler);
        self.push_callback(adapter);
    }

    pub async fn run(&mut self) -> eyre::Result<()> {
        let store = self.store.clone();
        let callbacks = self.callbacks.clone();
        let (task_tx, mut task_rx) = mpsc::unbounded_channel::<(String, i64, i64)>();
        let mut task_handle = tokio::spawn(async move {
            while let Some((aggregate_id, from, to)) = task_rx.recv().await {
                let envelopes = store.load_latest_events(&aggregate_id, from).await?;
                for envelope in envelopes.iter().filter(|e| e.sequence <= to) {
                    Self::run_callbacks(&envelope, &callbacks).await?;
                }
            }
            Ok::<_, eyre::Error>(())
        });

        let mut interval = tokio::time::interval(self.poll_interval);
        loop {
            tokio::select! {
                result = &mut task_handle => {
                    tracing::info!(agent = A::TYPE, result = ?result, "killed");
                    return result?
                },
                Ok(wake) = self.wake_rx.recv() => {
                    if wake.aggregate_type != A::TYPE {
                        continue;
                    }
                    if let Some(from) = self.process_from(&wake.aggregate_id, wake.current_sequence) {
                        self.send_task(&task_tx, &wake.aggregate_id, from, wake.current_sequence)?;
                    }
                },
                _ = interval.tick() => {
                    let candidates = self.store.load_sequence_nums::<A>().await?;
                    for (aggregate_id, to) in candidates.iter() {
                        if let Some(from) = self.process_from(&aggregate_id, *to) {
                            self.send_task(&task_tx, &aggregate_id, from, *to)?;
                        }
                    }
                },
                else => {
                    continue;
                }
            };
        }
    }

    pub async fn run_callbacks(event: &Envelope<A>, callbacks: &[ArcCallback<A>]) -> Result<()> {
        let mut set = tokio::task::JoinSet::new();
        for c in callbacks.iter().cloned() {
            let event = event.clone();
            set.spawn(async move { c.lock().await.process(&event).await });
        }
        while let Some(result) = set.join_next().await {
            result??;
        }
        Ok(())
    }

    fn process_from(&self, aggregate_id: &str, sequence: i64) -> Option<i64> {
        let current = *self.offsets.get(aggregate_id).unwrap_or(&0);
        if sequence > current {
            return Some(current);
        }
        None
    }

    fn send_task(
        &mut self,
        tx: &mpsc::UnboundedSender<(String, i64, i64)>,
        aggregate_id: &str,
        from: i64,
        to: i64,
    ) -> Result<()> {
        if tx.send((aggregate_id.to_string(), from, to)).is_err() {
            eyre::bail!("Callback processor task is dead")
        }
        self.offsets.insert(aggregate_id.to_string(), to);
        Ok(())
    }
}

struct CallbackAdapter<A, ES, H>
where
    A: Aggregate,
    ES: EventStore,
    H: EventHandler<A, ES>,
{
    handler: Handler<A, ES>,
    event_handler: H,
}

impl<A, ES, H> CallbackAdapter<A, ES, H>
where
    A: Aggregate,
    ES: EventStore,
    H: EventHandler<A, ES>,
{
    pub fn new(handler: Handler<A, ES>, event_handler: H) -> Self {
        Self {
            handler,
            event_handler,
        }
    }
}

impl<A: Aggregate, ES: EventStore, H: EventHandler<A, ES>> Callback<A>
    for CallbackAdapter<A, ES, H>
{
    async fn process(&mut self, event: &Envelope<A>) -> Result<()> {
        self.event_handler.process(&self.handler, event).await
    }
}

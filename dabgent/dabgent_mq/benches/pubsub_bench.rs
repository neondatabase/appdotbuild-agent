use criterion::{BenchmarkId, Criterion, criterion_group, criterion_main};
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_mq::*;
use serde::{Deserialize, Serialize};
use sqlx::sqlite::SqlitePool;
use std::sync::Arc;
use tokio::runtime::Runtime;
use tokio::sync::{Barrier, mpsc};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
struct BenchEvent {
    id: u64,
    payload: Vec<u8>,
}

impl Event for BenchEvent {
    fn event_version(&self) -> String {
        "1.0".to_owned()
    }
    fn event_type(&self) -> String {
        "BenchEvent".to_owned()
    }
}

#[derive(Debug, thiserror::Error)]
enum AggregateError {}

#[derive(Clone, Default)]
struct BenchAggregate;

impl Aggregate for BenchAggregate {
    const TYPE: &'static str = "bench_aggregate";
    type Command = ();
    type Error = AggregateError;
    type Event = BenchEvent;
    type Services = ();

    async fn handle(
        &self,
        _cmd: Self::Command,
        _services: &Self::Services,
    ) -> Result<Vec<Self::Event>, Self::Error> {
        Ok(Vec::new())
    }

    fn apply(&mut self, _event: Self::Event) {}
}

struct BenchCallback {
    total_seen: usize,
    tx: mpsc::UnboundedSender<usize>,
}

impl BenchCallback {
    fn new(tx: mpsc::UnboundedSender<usize>) -> Self {
        Self { total_seen: 0, tx }
    }
}

impl Callback<BenchAggregate> for BenchCallback {
    async fn process(&mut self, _: &Envelope<BenchAggregate>) -> eyre::Result<()> {
        self.total_seen += 1;
        let _ = self.tx.send(self.total_seen);
        Ok(())
    }
}

fn create_payload(size: usize) -> Vec<u8> {
    vec![0u8; size]
}

fn create_event(payload_size: usize) -> BenchEvent {
    BenchEvent {
        id: 1,
        payload: create_payload(payload_size),
    }
}

async fn create_store() -> SqliteStore {
    let pool = SqlitePool::connect("sqlite::memory:")
        .await
        .expect("Failed to create in-memory SQLite pool");
    let store = SqliteStore::new(pool, "bench_stream");
    store.migrate().await;
    store
}

fn bench_pubsub(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();

    let mut group = c.benchmark_group("pubsub");
    group.sample_size(10);

    let payload_sizes = [("1kb", 1024), ("4kb", 4 * 1024)];

    // name, num_aggregates, num_listeners, num_events
    let configurations = [
        ("1p_1c", 1, 1, 100),
        ("4p_4c", 4, 4, 100),
        ("1p_4c", 1, 4, 100),
        ("4p_1c", 4, 1, 100),
    ];

    for (size_name, payload_size) in &payload_sizes {
        for (config_name, num_aggregates, num_listeners, num_events) in &configurations {
            let bench_id = BenchmarkId::new(format!("{}_{}", size_name, config_name), payload_size);

            let total_messages = num_aggregates * num_events;
            group.throughput(criterion::Throughput::Elements(total_messages as u64));

            group.bench_function(bench_id, |b| {
                b.to_async(&rt).iter(|| async {
                    benchmark_scenario(*num_aggregates, *num_listeners, *num_events, *payload_size)
                        .await
                });
            });
        }
    }

    group.finish();
}

async fn benchmark_scenario(
    num_aggregates: usize,
    num_listeners: usize,
    num_events: usize,
    payload_size: usize,
) {
    let store = PollingQueue::new(create_store().await);
    let barrier = Arc::new(Barrier::new(num_aggregates + num_listeners + 1));
    let event = create_event(payload_size);

    let mut aggregate_handles = Vec::new();
    for aggregate_id in 0..num_aggregates {
        let store = store.clone();
        let barrier = barrier.clone();
        let event = event.clone();

        let handle = tokio::spawn(async move {
            barrier.wait().await;

            for event_id in 0..num_events {
                let ctx = AggregateContext {
                    aggregate_id: format!("aggregate-{}", aggregate_id),
                    aggregate: BenchAggregate::default(),
                    current_sequence: event_id as i64,
                };
                store
                    .commit(vec![event.clone()], Default::default(), ctx)
                    .await
                    .unwrap();
            }
        });

        aggregate_handles.push(handle);
    }

    let mut listener_handles = Vec::new();
    for _ in 0..num_listeners {
        let barrier = barrier.clone();
        let mut listener = store.listener::<BenchAggregate>();

        let handle = tokio::spawn(async move {
            let (tx, mut rx) = mpsc::unbounded_channel();
            listener.push_callback(BenchCallback::new(tx));
            tokio::spawn(async move {
                let _ = listener.run().await;
            });

            barrier.wait().await;

            let expected_events = num_aggregates * num_events;
            loop {
                match rx.recv().await {
                    Some(num) if num >= expected_events => break,
                    None => break,
                    _ => continue,
                }
            }
        });

        listener_handles.push(handle);
    }

    barrier.wait().await;

    for handle in aggregate_handles {
        handle.await.expect("Producer task failed");
    }

    for handle in listener_handles {
        handle.abort();
    }
}

criterion_group!(benches, bench_pubsub);
criterion_main!(benches);

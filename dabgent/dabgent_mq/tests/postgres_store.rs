use dabgent_mq::db::{postgres::PostgresStore, *};
use dabgent_mq::listener::PollingQueue;
use dabgent_mq::*;
use serde::{Deserialize, Serialize};
use sqlx::PgPool;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
enum TestEvent {
    Increment(usize),
    Decrement(usize),
}

impl Event for TestEvent {
    fn event_version(&self) -> String {
        "1.0".to_owned()
    }

    fn event_type(&self) -> String {
        "TestEvent".to_owned()
    }
}

#[derive(Debug, Clone, Copy)]
enum TestCommand {
    Increment(usize),
    Decrement(usize),
}

#[derive(Debug, thiserror::Error)]
enum TestError {
    #[error("Cannot decrement below zero")]
    DecrementBelowZero,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize, PartialEq)]
struct TestAggregate(usize);

impl Aggregate for TestAggregate {
    const TYPE: &'static str = "TestAggregate";
    type Command = TestCommand;
    type Event = TestEvent;
    type Error = TestError;
    type Services = ();

    async fn handle(
        &self,
        cmd: Self::Command,
        _services: &Self::Services,
    ) -> Result<Vec<Self::Event>, Self::Error> {
        match cmd {
            TestCommand::Increment(amount) => Ok(vec![TestEvent::Increment(amount)]),
            TestCommand::Decrement(amount) => {
                if self.0 < amount {
                    Err(TestError::DecrementBelowZero)
                } else {
                    Ok(vec![TestEvent::Decrement(amount)])
                }
            }
        }
    }

    fn apply(&mut self, event: Self::Event) {
        match event {
            TestEvent::Increment(amount) => self.0 += amount,
            TestEvent::Decrement(amount) => self.0 -= amount,
        }
    }
}

struct TestCallback<ES: EventStore> {
    handler: Handler<TestAggregate, ES>,
    tx: tokio::sync::mpsc::UnboundedSender<()>,
}

impl<ES: EventStore> Callback<TestAggregate> for TestCallback<ES> {
    async fn process(&mut self, event: &dabgent_mq::Envelope<TestAggregate>) -> eyre::Result<()> {
        match event.data {
            TestEvent::Increment(..) => {
                let result = self
                    .handler
                    .execute(&event.aggregate_id, TestCommand::Decrement(1))
                    .await;
                let _ = self.tx.send(());
                result.map_err(Into::into)
            }
            _ => Ok(()),
        }
    }
}

async fn setup_test_store() -> PostgresStore {
    let dsn = std::env::var("DATABASE_URL").unwrap();
    let pool = PgPool::connect(&dsn)
        .await
        .expect("Failed to connect to PostgreSQL");
    let store = PostgresStore::new(pool, "test_stream");
    store.migrate().await;
    store
}

#[tokio::test]
async fn test_handler_commands() {
    let store = setup_test_store().await;
    let aggregate_id = "test-aggregate";
    let handler = Handler::<TestAggregate, _>::new(store.clone(), ());

    let command = TestCommand::Increment(3);
    handler
        .execute(aggregate_id, command)
        .await
        .expect("Failed to execute command");

    handler
        .execute(aggregate_id, command)
        .await
        .expect("Failed to execute command");

    let ctx = store
        .load_aggregate::<TestAggregate>(aggregate_id)
        .await
        .expect("Failed to load aggregate");
    assert_eq!(ctx.aggregate.0, 6);
    assert_eq!(ctx.current_sequence, 2);
}

#[tokio::test]
async fn test_latest_sequences() {
    let store = setup_test_store().await;
    let aggregate_id = "test-aggregate";
    let handler = Handler::<TestAggregate, _>::new(store.clone(), ());

    let latest_sequences = store
        .load_sequence_nums::<TestAggregate>()
        .await
        .expect("Failed to load sequence numbers");
    assert!(latest_sequences.is_empty());

    let command = TestCommand::Increment(3);
    handler
        .execute(aggregate_id, command)
        .await
        .expect("Failed to execute command");

    let mut latest_sequences = store
        .load_sequence_nums::<TestAggregate>()
        .await
        .expect("Failed to load sequence numbers");
    assert_eq!(latest_sequences.len(), 1);
    let (id, sequence) = latest_sequences.pop().unwrap();
    assert_eq!(id, aggregate_id);
    assert_eq!(sequence, 1);
}

#[tokio::test]
async fn test_single_callback() {
    let store = PollingQueue::new(setup_test_store().await);
    let aggregate_id = "test-aggregate";
    let handler = Handler::<TestAggregate, _>::new(store.clone(), ());

    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
    let callback = TestCallback {
        handler: handler.clone(),
        tx,
    };

    let mut listener = store.listener();
    listener.push_callback(callback);

    tokio::spawn(async move {
        let _ = listener.run().await;
    });

    handler
        .execute(aggregate_id, TestCommand::Increment(3))
        .await
        .expect("Failed to execute command");
    let _ = rx.recv().await;
    let ctx = store
        .load_aggregate::<TestAggregate>(aggregate_id)
        .await
        .expect("Failed to load aggregate");
    assert_eq!(ctx.current_sequence, 2);
    assert_eq!(ctx.aggregate.0, 2);
}

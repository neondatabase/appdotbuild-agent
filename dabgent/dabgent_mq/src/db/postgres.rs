use super::*;
use sqlx::PgPool;

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations/postgres");

#[derive(Clone)]
pub struct PostgresStore {
    pool: PgPool,
    stream_id: String,
}

impl PostgresStore {
    pub fn new<T: AsRef<str>>(pool: PgPool, stream_id: T) -> Self {
        Self {
            pool,
            stream_id: stream_id.as_ref().to_string(),
        }
    }

    pub async fn migrate(&self) {
        MIGRATOR.run(&self.pool).await.expect("Migration failed")
    }

    fn select_query<T: AsRef<str>>(
        &self,
        aggregate_type: T,
        aggregate_id: Option<T>,
        offset: Option<i64>,
    ) -> (String, Vec<String>) {
        let mut conditions = vec![
            "stream_id = $1".to_owned(),
            "aggregate_type = $2".to_owned(),
        ];
        let mut params = vec![self.stream_id.clone(), aggregate_type.as_ref().to_string()];
        let mut param_count = 2;

        if let Some(aggregate_id) = aggregate_id {
            param_count += 1;
            conditions.push(format!("aggregate_id = ${}", param_count));
            params.push(aggregate_id.as_ref().to_string());
        }
        if let Some(offset) = offset {
            param_count += 1;
            conditions.push(format!("sequence > ${}", param_count));
            params.push(offset.to_string());
        }
        let where_clause = conditions.join(" AND ");
        let sql = format!("SELECT * FROM events WHERE {where_clause} ORDER BY sequence ASC");
        (sql, params)
    }
}

impl EventStore for PostgresStore {
    async fn commit<A: Aggregate>(
        &self,
        events: Vec<A::Event>,
        metadata: Metadata,
        context: AggregateContext<A>,
    ) -> Result<Vec<Envelope<A>>, Error> {
        let wrapped = wrap_events::<A>(
            &context.aggregate_id,
            context.current_sequence,
            events,
            metadata,
        );
        let serialized = wrapped
            .iter()
            .map(SerializedEvent::try_from)
            .collect::<Result<Vec<_>, _>>()?;
        let mut tx = self.pool.begin().await.map_err(Error::Database)?;
        for event in serialized.into_iter() {
            sqlx::query(
                r#"
                INSERT INTO events (stream_id, aggregate_type, aggregate_id, sequence, event_type, event_version, data, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
                "#
            )
            .bind(&self.stream_id)
            .bind(A::TYPE)
            .bind(event.aggregate_id)
            .bind(event.sequence)
            .bind(event.event_type)
            .bind(event.event_version)
            .bind(event.data)
            .bind(event.metadata)
            .execute(&mut *tx)
            .await
            .map_err(Error::Database)?;
        }
        tx.commit().await.map_err(Error::Database)?;
        Ok(wrapped)
    }

    async fn load_aggregate<A: Aggregate>(
        &self,
        aggregate_id: &str,
    ) -> Result<AggregateContext<A>, Error> {
        let events = self.load_events::<A>(aggregate_id).await?;
        let mut aggregate = A::default();
        let mut current_sequence = 0;
        for event in events {
            current_sequence = event.sequence;
            aggregate.apply(event.data)
        }
        Ok(AggregateContext {
            aggregate_id: aggregate_id.to_owned(),
            current_sequence,
            aggregate,
        })
    }

    async fn load_events<A: Aggregate>(
        &self,
        aggregate_id: &str,
    ) -> Result<Vec<Envelope<A>>, Error> {
        let (sql, params) = self.select_query(A::TYPE, Some(aggregate_id), None);
        let mut query = sqlx::query_as::<_, SerializedEvent>(&sql);
        for param in params {
            query = query.bind(param);
        }
        let serialized = query.fetch_all(&self.pool).await.map_err(Error::Database)?;
        serialized
            .into_iter()
            .map(Envelope::try_from)
            .collect::<Result<Vec<_>, _>>()
    }

    async fn load_latest_events<A: Aggregate>(
        &self,
        aggregate_id: &str,
        sequence_from: i64,
    ) -> Result<Vec<Envelope<A>>, Error> {
        let serialized = sqlx::query_as::<_, SerializedEvent>(
            r#"SELECT * FROM events WHERE stream_id = $1 AND aggregate_type = $2 AND aggregate_id = $3 AND sequence > $4 ORDER BY sequence ASC"#
        )
        .bind(&self.stream_id)
        .bind(A::TYPE)
        .bind(aggregate_id)
        .bind(sequence_from)
        .fetch_all(&self.pool)
        .await
        .map_err(Error::Database)?;

        serialized
            .into_iter()
            .map(Envelope::try_from)
            .collect::<Result<Vec<_>, _>>()
    }

    async fn load_sequence_nums<A: Aggregate>(&self) -> Result<Vec<(String, i64)>, Error> {
        sqlx::query_as::<_, (String, i64)>(
            r#"SELECT aggregate_id, MAX(sequence) FROM events WHERE stream_id = $1 AND aggregate_type = $2 GROUP BY aggregate_id;"#
        )
        .bind(&self.stream_id)
        .bind(A::TYPE)
        .fetch_all(&self.pool)
        .await
        .map_err(Error::Database)
    }
}

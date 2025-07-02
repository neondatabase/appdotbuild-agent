import uuid
import dagger

def create_postgres_service(client: dagger.Client) -> dagger.Service:
    """Create a PostgreSQL service with unique instance ID."""
    return (
        client.container()
        .from_("postgres:17.0-alpine")
        .with_env_variable("POSTGRES_USER", "postgres")
        .with_env_variable("POSTGRES_PASSWORD", "postgres")
        .with_env_variable("POSTGRES_DB", "postgres")
        .with_env_variable("INSTANCE_ID", uuid.uuid4().hex)
        .as_service(use_entrypoint=True)
    )

def pg_health_check_cmd(timeout: int = 30):
    return [
        "sh", "-c",
        f"for i in $(seq 1 {timeout}); do "
        "pg_isready -h postgres -U postgres && exit 0; "
        "echo 'Waiting for PostgreSQL...' && sleep 1; "
        "done; exit 1"
    ]

# Rust Web Application

A web application built with Axum, Diesel, and HTMX.

## Stack

- **Axum**: Fast, ergonomic web framework for Rust
- **Diesel**: Safe, extensible ORM and Query Builder
- **HTMX**: High power tools for HTML
- **PostgreSQL**: Robust relational database

## Development

### Prerequisites

- Rust 1.82+
- PostgreSQL
- Docker (optional)

### Setup

```bash
# Install Diesel CLI
cargo install diesel_cli --no-default-features --features postgres

# Set up database
export DATABASE_URL=postgres://postgres:postgres@localhost:5432/postgres
diesel migration run

# Run the application
cargo run
```

### Docker

```bash
docker-compose up
```

The application will be available at http://localhost:3000

### Database Migrations

```bash
# Generate a new migration
diesel migration generate create_users

# Apply migrations
diesel migration run

# Revert last migration
diesel migration revert
```

## API Endpoints

- `GET /` - Main page
- `GET /health` - Health check
- Additional endpoints will be generated based on your data models
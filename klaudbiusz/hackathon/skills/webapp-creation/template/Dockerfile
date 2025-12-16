# syntax=docker/dockerfile:1
FROM rust:1.92-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY migrations ./migrations
COPY templates ./templates
COPY .sqlx ./.sqlx
ENV SQLX_OFFLINE=true
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release && cp target/release/webapp /webapp

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates libssl3 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /webapp .
COPY templates ./templates
COPY static ./static
COPY migrations ./migrations
COPY .env* ./
EXPOSE 80
ENV PORT=80
CMD ["./webapp"]

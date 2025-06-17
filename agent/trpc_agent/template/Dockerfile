# Build stage
FROM oven/bun:1.2.2-alpine AS builder

# Set working directory
WORKDIR /app

# Copy package.json and lockfile
COPY package.json bun.lock ./

# Create directories for client and server
RUN mkdir -p client server

# Copy package.json for client and server
COPY client/package.json ./client/
COPY server/package.json ./server/

# Install all dependencies
RUN bun install --frozen-lockfile

# Copy the entire project
COPY . .

# Build client
RUN cd client && bun run build

# Build server
RUN cd server && bun run build

# Production stage
FROM oven/bun:1.2.2-alpine

# Env vars for the end image should be here
ENV APP_DATABASE_URL=${APP_DATABASE_URL}
ENV SERVER_PORT=${SERVER_PORT:-2022}
# Install curl for healthcheck, Caddy, and supervisor
RUN apk add --no-cache curl caddy supervisor

WORKDIR /app

# Copy built client files and Caddyfile
COPY --from=builder /app/client/ /app/client/
COPY --from=builder /app/client/Caddyfile /app/client/Caddyfile

# Copy server files
COPY --from=builder /app/server/ /app/server/
COPY --from=builder /app/server/package.json /app/server/

# Copy root package.json
COPY --from=builder /app/package.json /app

# Install server dependencies
WORKDIR /app/server
RUN bun install --frozen-lockfile

# Configure supervisor
WORKDIR /app
COPY supervisord.conf /etc/supervisord.conf

EXPOSE ${SERVER_PORT} 80

CMD ["sh", "-c", "bun db:push-ci && /usr/bin/supervisord -c /etc/supervisord.conf"]
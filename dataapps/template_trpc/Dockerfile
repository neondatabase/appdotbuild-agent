# Multi-stage Dockerfile for tRPC template
FROM node:20-alpine3.22 AS builder

WORKDIR /app

# Copy all package files (may not have lock files if agent modified deps)
COPY client/package*.json ./client/
COPY server/package*.json ./server/

# Install all dependencies with BuildKit cache mount
# Note: Using npm install (not npm ci) in build stage because:
# - Agent may add new dependencies to package.json during development
# - package-lock.json may be missing or out of sync
# - npm install will generate/update the lock file
# The generated lock file is then copied to production stage for reproducible builds
RUN --mount=type=cache,target=/root/.npm \
    cd client && npm install

RUN --mount=type=cache,target=/root/.npm \
    cd server && npm install

# Copy server source (needed for client build due to tRPC types)
COPY server/ ./server/

# Copy client source and build
COPY client/ ./client/
RUN cd client && npm run build

# Stage 2: Production image
FROM node:20-alpine3.22

# Install curl for healthcheck
RUN apk add --no-cache curl

WORKDIR /app

# Copy package files including the lock file generated in build stage
# This ensures reproducible production builds with exact dependency versions
COPY --from=builder /app/server/package*.json ./server/
RUN --mount=type=cache,target=/root/.npm \
    cd server && npm ci --omit=dev

# Copy server source
COPY server/ ./server/

# Copy built client from builder stage
RUN mkdir -p server/public
COPY --from=builder /app/client/dist/ ./server/public/

# Set working directory to server
WORKDIR /app/server

# Expose port
EXPOSE 8000

# Start the application
CMD ["npm", "start"]

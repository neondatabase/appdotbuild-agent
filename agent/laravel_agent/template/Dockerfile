# Multi-stage Dockerfile for Laravel with React/Inertia.js

# Stage 1: Build frontend assets
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install node dependencies
RUN npm ci --only=production

# Copy source code
COPY . .

# Build frontend assets
RUN npm run build

# Stage 2: PHP base with extensions
FROM php:8.2-fpm-alpine AS php-base

# Install system dependencies and PHP extensions
RUN apk add --no-cache \
    nginx \
    supervisor \
    postgresql-dev \
    oniguruma-dev \
    libzip-dev \
    freetype-dev \
    libjpeg-turbo-dev \
    libpng-dev \
    curl-dev \
    libxml2-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install \
    pdo \
    pdo_pgsql \
    pdo_mysql \
    mysqli \
    mbstring \
    zip \
    exif \
    pcntl \
    gd \
    bcmath \
    opcache \
    curl \
    xml \
    soap

# Install Composer
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

# Stage 3: Application build
FROM php-base AS app-builder

WORKDIR /var/www/html

# Copy application code
COPY . .

# Install PHP dependencies
RUN composer install --no-dev --optimize-autoloader --no-interaction

# Copy built frontend assets from frontend-builder stage
COPY --from=frontend-builder /app/public/build ./public/build

# Set proper permissions
RUN chown -R www-data:www-data /var/www/html \
    && chmod -R 755 /var/www/html/storage \
    && chmod -R 755 /var/www/html/bootstrap/cache

# Stage 4: Production runtime
FROM php-base AS production

WORKDIR /var/www/html

# Set production environment variables (can be overridden at runtime)
ENV APP_ENV=${APP_ENV:-production}
ENV APP_DEBUG=${APP_DEBUG:-false}
ENV APP_DATABASE_URL=${APP_DATABASE_URL}
ENV DB_MIGRATION_URL=${DB_MIGRATION_URL}
ENV APP_KEY=${APP_KEY}


# Copy application from builder
COPY --from=app-builder --chown=www-data:www-data /var/www/html .

# Copy configuration files
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/php-fpm.conf /usr/local/etc/php-fpm.d/www.conf
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/php.ini /usr/local/etc/php/conf.d/99-custom.ini
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# Create required directories and set permissions
RUN mkdir -p /var/log/supervisor \
    && mkdir -p /run/nginx \
    && mkdir -p /var/www/html/storage/logs \
    && mkdir -p /var/www/html/storage/framework/cache \
    && mkdir -p /var/www/html/storage/framework/sessions \
    && mkdir -p /var/www/html/storage/framework/views \
    && chown -R www-data:www-data /var/www/html/storage \
    && chmod -R 775 /var/www/html/storage \
    && chmod +x /usr/local/bin/entrypoint.sh

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost/ || exit 1


# Use entrypoint script to run migrations and start services
CMD ["/usr/local/bin/entrypoint.sh"] 
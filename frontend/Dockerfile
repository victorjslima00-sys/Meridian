# Multi-stage Dockerfile for Meridian Frontend Dashboard
# Stage 1: Build stage using official Node 22 Alpine
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies using pinned package-lock.json
COPY package.json package-lock.json ./
RUN npm ci

# Copy full frontend source code and compile production assets
COPY . .
RUN npm run build

# Stage 2: Runtime stage using minimal Nginx web server
FROM nginx:alpine

# Copy compiled static assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose standard web port
EXPOSE 80

# Run nginx in foreground (no npm ci or npm run build at container start)
CMD ["nginx", "-g", "daemon off;"]

# NetClaw Dockerfile - Built on OpenClaw
# Build context: the netclaw/ submodule directory
FROM node:22-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pnpm (required for OpenClaw build)
RUN npm install -g pnpm

# Set working directory
WORKDIR /app

# Install OpenClaw globally (pre-built)
RUN npm install -g openclaw@latest --ignore-engines

# Copy NetClaw submodule contents
COPY . /app/netclaw/

# Install NetClaw MCP servers
RUN cd /app/netclaw && \
    if [ -f "scripts/install.sh" ]; then \
        chmod +x scripts/install.sh && \
        ./scripts/install.sh; \
    fi

# Create workspace directory
RUN mkdir -p /app/workspace

# Set environment variables
ENV OPENCLAW_MODE=gateway
ENV NODE_ENV=production
ENV NETCLAW_LAB_MODE=false

# Expose ports
EXPOSE 18789 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:18789/health || exit 1

# Start OpenClaw gateway
CMD ["openclaw", "gateway", "run"]

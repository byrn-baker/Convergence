ARG NAUTOBOT_VERSION=3.0.5-py3.12
FROM networktocode/nautobot:${NAUTOBOT_VERSION}

# Switch to root for installation
USER root

# Set working directory
WORKDIR /opt/nautobot

# Install Poetry globally
RUN pip install --no-cache-dir --upgrade pip poetry

# Add poetry to PATH
ENV PATH="/root/.local/bin:${PATH}"

# Copy pyproject.toml for app dependencies
COPY pyproject.toml /opt/nautobot/

# Install Nautobot apps using Poetry
# Use --no-root since we're not installing a package, just dependencies
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --no-interaction --no-ansi

# Copy Nautobot configuration
COPY nautobot_config.py /opt/nautobot/

# Copy chatbot plugin
COPY nautobot_chatbot/ /opt/nautobot/nautobot_chatbot/

# Ensure permissions are correct
RUN chown -R nautobot:nautobot /opt/nautobot

# Switch back to nautobot user
USER nautobot

# Run migrations and collect static files on startup
CMD ["nautobot-server", "start", "--ini", "/opt/nautobot/uwsgi.ini"]

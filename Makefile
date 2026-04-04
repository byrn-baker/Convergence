.PHONY: help up down restart logs health clean build pull ps stats status debug-otel debug-metrics debug-endpoints

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)Convergence Platform - Available Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

# ============================================================================
# Docker Management
# ============================================================================

up: ## Start all services
	@echo "$(BLUE)Starting Convergence platform...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)✓ Platform started$(NC)"
	@echo ""
	@echo "Access points:"
	@echo "  Grafana:         http://localhost:3000 (admin/admin)"
	@echo "  VictoriaMetrics: http://localhost:8428"
	@echo "  OTEL Collector:  http://localhost:8888/metrics"

down: ## Stop all services
	@echo "$(BLUE)Stopping Convergence platform...$(NC)"
	docker-compose down
	@echo "$(GREEN)✓ Platform stopped$(NC)"

restart: ## Restart all services
	@echo "$(BLUE)Restarting Convergence platform...$(NC)"
	docker-compose restart
	@echo "$(GREEN)✓ Platform restarted$(NC)"

logs: ## View logs from all services
	docker-compose logs -f

logs-otel: ## View OTEL Collector logs
	docker-compose logs -f otel-collector

logs-vm: ## View VictoriaMetrics logs
	docker-compose logs -f victoriametrics

logs-grafana: ## View Grafana logs
	docker-compose logs -f grafana

health: ## Check health of all services
	@echo "$(BLUE)Checking service health...$(NC)"
	@docker-compose ps
	@echo ""
	@echo "$(BLUE)Testing endpoints...$(NC)"
	@curl -sf http://localhost:3000/api/health > /dev/null && echo "$(GREEN)✓ Grafana is healthy$(NC)" || echo "$(RED)✗ Grafana is unhealthy$(NC)"
	@curl -sf http://localhost:8428/health > /dev/null && echo "$(GREEN)✓ VictoriaMetrics is healthy$(NC)" || echo "$(RED)✗ VictoriaMetrics is unhealthy$(NC)"
	@curl -sf http://localhost:13133/ > /dev/null && echo "$(GREEN)✓ OTEL Collector is healthy$(NC)" || echo "$(RED)✗ OTEL Collector is unhealthy$(NC)"

clean: ## Clean up all data and volumes
	@echo "$(YELLOW)⚠ This will delete all data! Are you sure? [y/N]$(NC)" && read ans && [ $${ans:-N} = y ]
	@echo "$(BLUE)Cleaning up...$(NC)"
	docker-compose down -v
	rm -rf data/
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

# ============================================================================
# Development Helpers
# ============================================================================

build: ## Build Docker images
	@echo "$(BLUE)Building Docker images...$(NC)"
	docker-compose build
	@echo "$(GREEN)✓ Images built$(NC)"

pull: ## Pull latest Docker images
	@echo "$(BLUE)Pulling latest images...$(NC)"
	docker-compose pull
	@echo "$(GREEN)✓ Images pulled$(NC)"

ps: ## Show running containers
	docker-compose ps

stats: ## Show container resource usage
	docker stats $$(docker-compose ps -q)

status: ## Show comprehensive status
	@echo "$(BLUE)=== Convergence Platform Status ===$(NC)"
	@echo ""
	@make health
	@echo ""
	@echo "$(BLUE)Docker Containers:$(NC)"
	@docker-compose ps
	@echo ""
	@echo "$(BLUE)Disk Usage:$(NC)"
	@docker system df

# ============================================================================
# Troubleshooting
# ============================================================================

debug-otel: ## Debug OTEL Collector configuration
	@echo "$(BLUE)Testing OTEL Collector configuration...$(NC)"
	docker-compose exec otel-collector /otelcol --config=/etc/otelcol/config.yaml --dry-run

debug-metrics: ## Show current metrics in VictoriaMetrics
	@echo "$(BLUE)Querying VictoriaMetrics...$(NC)"
	@curl -s "http://localhost:8428/api/v1/label/__name__/values" | python3 -m json.tool

debug-endpoints: ## Test all HTTP endpoints
	@echo "$(BLUE)Testing HTTP endpoints...$(NC)"
	@echo "Grafana API:"
	@curl -s http://localhost:3000/api/health | python3 -m json.tool || echo "Failed"
	@echo ""
	@echo "VictoriaMetrics:"
	@curl -s http://localhost:8428/health || echo "Failed"
	@echo ""
	@echo "OTEL Collector:"
	@curl -s http://localhost:13133/ || echo "Failed"

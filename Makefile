.PHONY: help install dev test lint format clean docker-build docker-up docker-down k8s-deploy k8s-delete demo

# Default target
.DEFAULT_GOAL := help

# Variables
PYTHON := python3
PIP := pip3
DOCKER_COMPOSE := docker-compose
KUBECTL := kubectl
NAMESPACE := customer-service
IMAGE_NAME := gcr.io/YOUR_PROJECT_ID/multi-agent-cs
IMAGE_TAG := latest

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies
	$(PIP) install -r requirements.txt

dev: ## Run development server
	$(PYTHON) -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

test: ## Run tests
	pytest tests/ -v --cov=. --cov-report=html

lint: ## Run linting
	ruff check .
	mypy . --ignore-missing-imports

format: ## Format code
	black .
	ruff check . --fix

clean: ## Clean up temporary files
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.coverage" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .mypy_cache
	rm -rf .ruff_cache

docker-build: ## Build Docker image
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-push: docker-build ## Push Docker image to registry
	docker push $(IMAGE_NAME):$(IMAGE_TAG)

docker-up: ## Start services with Docker Compose
	$(DOCKER_COMPOSE) up -d

docker-down: ## Stop services
	$(DOCKER_COMPOSE) down

docker-logs: ## Show logs from all services
	$(DOCKER_COMPOSE) logs -f

docker-clean: docker-down ## Clean up Docker resources
	$(DOCKER_COMPOSE) down -v
	docker system prune -f

k8s-create-namespace: ## Create Kubernetes namespace
	$(KUBECTL) apply -f kubernetes/namespace.yaml

k8s-create-secrets: k8s-create-namespace ## Create Kubernetes secrets
	@echo "Creating secrets..."
	@echo "Make sure to update kubernetes/secret.yaml with actual values"
	$(KUBECTL) apply -f kubernetes/secret.yaml

k8s-deploy: k8s-create-secrets ## Deploy to Kubernetes
	$(KUBECTL) apply -f kubernetes/configmap.yaml
	$(KUBECTL) apply -f kubernetes/redis.yaml
	$(KUBECTL) apply -f kubernetes/postgres.yaml
	$(KUBECTL) apply -f kubernetes/deployment.yaml
	$(KUBECTL) apply -f kubernetes/service.yaml
	$(KUBECTL) apply -f kubernetes/hpa.yaml

k8s-delete: ## Delete Kubernetes deployment
	$(KUBECTL) delete namespace $(NAMESPACE)

k8s-status: ## Check deployment status
	$(KUBECTL) get all -n $(NAMESPACE)
	$(KUBECTL) get ingress -n $(NAMESPACE)

k8s-logs: ## Show application logs
	$(KUBECTL) logs -n $(NAMESPACE) -l app=multi-agent-cs --tail=100 -f

demo: ## Run demo scenarios
	$(PYTHON) demo.py

monitoring-up: ## Start monitoring stack
	$(DOCKER_COMPOSE) up -d prometheus grafana

monitoring-down: ## Stop monitoring stack
	$(DOCKER_COMPOSE) stop prometheus grafana

health-check: ## Check system health
	curl -s http://localhost:8000/api/v1/system/health | jq .

metrics: ## Show system metrics
	curl -s http://localhost:8000/api/v1/system/metrics | jq .

create-migration: ## Create database migration
	alembic revision --autogenerate -m "$(message)"

migrate: ## Run database migrations
	alembic upgrade head

rollback: ## Rollback last migration
	alembic downgrade -1

shell: ## Open Python shell with app context
	$(PYTHON) -i -c "from main import *"

docs: ## Generate documentation
	cd docs && make html

serve-docs: docs ## Serve documentation locally
	cd docs/_build/html && $(PYTHON) -m http.server 8080
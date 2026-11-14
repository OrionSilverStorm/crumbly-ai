# Crumbly developer commands. Windows: run from Git Bash (uses .venv/Scripts); macOS/Linux use .venv/bin.
PY := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python,.venv/bin/python)
PORT ?= 8000
SCENARIO ?= happy

.PHONY: install build dev test reset send-cancellation bot uc-setup deploy

install:          ## Python venv + frontend packages
	python -m venv .venv && $(PY) -m pip install -r requirements.txt
	cd frontend && npm install

build:            ## Build the React app into frontend/dist (served by FastAPI)
	cd frontend && npm run build

dev: build        ## Run the whole app locally on http://localhost:$(PORT)
	$(PY) -m uvicorn backend.main:app --port $(PORT)

test:             ## Offline test suite (embedded Postgres, in-memory mail, stub LLM, Linkup fixtures)
	$(PY) -m pytest

reset:            ## Reset demo data, mailboxes and scenario (make reset SCENARIO=short_confirm)
	curl -s -X POST localhost:$(PORT)/api/demo/reset -H 'content-type: application/json' -d '{"scenario":"$(SCENARIO)"}' \
	  || $(PY) -m backend.demo.reset $(SCENARIO)

send-cancellation: ## Email the Millers Supply cancellation to the bakery inbox (the demo trigger)
	curl -s -X POST localhost:$(PORT)/api/demo/send-cancellation

bot:              ## Run the supplier bot as its own process (set SUPPLIER_BOT_INPROCESS=0 for the app)
	$(PY) -m backend.demo.supplier_bot

uc-setup:         ## Create Delta tables + UC functions in the workspace (WAREHOUSE_MODE=databricks)
	WAREHOUSE_MODE=databricks $(PY) -c "from backend.dbx import sql; sql.setup()"

deploy: build     ## Deploy as a Databricks App (needs the Databricks CLI, logged in)
	databricks sync . /Workspace/Shared/crumbly --exclude-from .gitignore --include frontend/dist
	databricks apps deploy crumbly --source-code-path /Workspace/Shared/crumbly

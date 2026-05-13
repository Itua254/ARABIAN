# ─────────────────────────────────────────────────────────────
# Makefile — Ebitrate Arb Bot Dev Commands
# ─────────────────────────────────────────────────────────────
PYTHON  = venv/bin/python
PIP     = venv/bin/pip
PYTEST  = venv/bin/pytest

.PHONY: install run paper limited full test replay metrics clean

## install: Create venv and install all dependencies
install:
	python3 -m venv venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PYTHON) -m playwright install chromium --with-deps

## redis-up: Start a local Redis container using Docker
redis-up:
	@echo "Starting local Redis container..."
	docker run -d --name ebitrate-redis -p 6379:6379 redis:7-alpine || echo "Redis may already be running."

## run / paper: Launch engine in paper mode (default)
run: paper
paper:
	EXECUTION_MODE=paper DRY_RUN=True $(PYTHON) main.py

## limited: Launch engine in limited mode (real bets, capped at $5)
limited:
	EXECUTION_MODE=limited DRY_RUN=False $(PYTHON) main.py

## full: Launch engine in full production mode — USE WITH CAUTION
full:
	@echo "WARNING: Full mode — real bets will be placed."
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ]
	EXECUTION_MODE=full DRY_RUN=False $(PYTHON) main.py

## test: Run full test suite
test:
	$(PYTEST) tests/ -v --tb=short

## test-fast: Run tests without slow IO tests
test-fast:
	$(PYTEST) tests/ -v --tb=short -m "not slow"

## replay: Re-run trade journal through current rules
replay:
	$(PYTHON) replay_engine.py

## metrics: Show current metrics snapshot
metrics:
	@if [ -f metrics_snapshot.json ]; then \
		cat metrics_snapshot.json | python3 -m json.tool; \
	else \
		echo "No metrics snapshot found. Run the engine first."; \
	fi

## status: Show system status (journal counts, burned accounts, profiles)
status:
	@echo "=== Trade Journal ===" && \
	$(PYTHON) -c "import json; j=json.load(open('trade_journal.json')) if __import__('os').path.exists('trade_journal.json') else []; print(f'  Trades recorded: {len(j)}')" 2>/dev/null || echo "  No journal yet."
	@echo "=== Burned Accounts ===" && \
	$(PYTHON) -c "import json; b=json.load(open('burned_accounts.json')) if __import__('os').path.exists('burned_accounts.json') else []; print(f'  Burned: {b}')" 2>/dev/null || echo "  None."
	@echo "=== Bookmaker Profiles ===" && \
	$(PYTHON) -c "import json; p=json.load(open('bookmaker_profiles.json')) if __import__('os').path.exists('bookmaker_profiles.json') else {}; [print(f'  {k}: health={v[\"health_score\"]:.2f}') for k,v in p.items()]" 2>/dev/null || echo "  No profiles yet."

## logs: Tail the live log
logs:
	tail -f arb_bot.log

## events: Tail the structured event stream
events:
	tail -f events.jsonl | python3 -m json.tool

## clean: Remove generated files (keep journals and logs)
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -f metrics_snapshot.json replay_report.json

## clean-all: Remove ALL generated state (destructive!)
clean-all: clean
	@echo "WARNING: This will delete journals, profiles, and burned accounts."
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ]
	rm -f trade_journal.json trade_journal_latency.json hedge_journal.json \
	      bookmaker_profiles.json burned_accounts.json events.jsonl arb_bot.log \
	      state_*.json

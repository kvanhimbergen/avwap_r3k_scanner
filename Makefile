PYTEST := ./venv/bin/pytest

.PHONY: test test-core test-analytics test-all

# Default: the fast core suite — strategies, ops, analytics modules.
test: test-core

# Strategies / ops / analytics modules. Excludes the FastAPI analytics_platform
# tests because they pull in fastapi/httpx fixtures that pollute the warnings
# stream — keeping them separate lets the core run stay fast and quiet.
test-core:
	$(PYTEST) tests/ --ignore=tests/analytics_platform -q

# FastAPI / dashboard backend tests. ~120 tests, slightly slower, noisier.
test-analytics:
	$(PYTEST) tests/analytics_platform/ -q

# Full coverage. Use before commits that touch shared code.
test-all: test-core test-analytics

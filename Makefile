LINT_FIX = 1
COVERAGE = 0

.PHONY: lint_ruff
lint_ruff:
ifeq ($(LINT_FIX),1)
	ruff . --fix
else
	ruff .
endif

.PHONY: lint_black
lint_black:
ifeq ($(LINT_FIX),1)
	black .
else
	black --check .
endif

.PHONY: lint_mypy
lint_mypy:
	mypy . --check-untyped-defs

.PHONY: lint
lint: lint_ruff lint_black lint_mypy

.PHONY: test
test:
ifeq ($(COVERAGE),0)
	pytest tests
else
	pytest --no-cov-on-fail --cov=distributed_lock --cov-report=term --cov-report=html --cov-report=xml tests
endif

.PHONY: apidoc
apidoc:
	@rm -Rf apihtml
	pdoc -d google -o apihtml distributed_lock

.PHONY: clean
clean:
	rm -Rf apihtml htmlcov
	rm -Rf .mypy_cache .ruff_cache .pytest_cache 
	find . -type d -name __pycache__ -exec rm -Rf {} \; 2>/dev/null || true

.PHONY: bump_version
bump_version:
	python ./bump_version.py
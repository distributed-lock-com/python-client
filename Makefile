LINT_FIX = 1

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

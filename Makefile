PY := .venv/bin/python

.PHONY: setup test

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest -q

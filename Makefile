PY := .venv/bin/python

.PHONY: setup schema test

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

schema:
	$(PY) -m factory.db

test:
	$(PY) -m pytest -q

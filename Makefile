PY := .venv/bin/python

.PHONY: setup schema build checks test

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

schema:
	$(PY) -m factory.db

build:
	$(PY) -m factory.build

checks:
	$(PY) -m factory.checks

test:
	$(PY) -m pytest -q

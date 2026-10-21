PY := .venv/bin/python

.PHONY: setup schema build test

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

schema:
	$(PY) -m factory.db

build:
	$(PY) -m factory.build

test:
	$(PY) -m pytest -q

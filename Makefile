PY := .venv/bin/python

.PHONY: setup schema views build checks test

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

schema:
	$(PY) -m factory.db

views:
	$(PY) -c "from factory.db import connect, apply_views; c = connect(); apply_views(c)"

build:
	$(PY) -m factory.build

checks:
	$(PY) -m factory.checks

test:
	$(PY) -m pytest -q

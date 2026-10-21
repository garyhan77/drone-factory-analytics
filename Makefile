PY := .venv/bin/python

.PHONY: setup schema views build build-remote create-readonly-role verify-hosting checks run test

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

schema:
	$(PY) -m factory.db

views:
	$(PY) -c "from factory.db import connect, apply_views; c = connect(); apply_views(c)"

build:
	$(PY) -m factory.build

# Hosted database: DATABASE_URL must be the admin string, exported in your shell (never written to a file).
build-remote:
	$(PY) -m factory.build --remote --grant-to app_readonly

create-readonly-role:
	$(PY) -m factory.hosting create-role

verify-hosting:
	$(PY) -m factory.hosting verify

checks:
	$(PY) -m factory.checks

run:
	.venv/bin/streamlit run app/Home.py

test:
	$(PY) -m pytest -q

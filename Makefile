.PHONY: dogfood test

dogfood:
	uv run python scripts/dogfood_nowadays.py

test:
	uv run pytest

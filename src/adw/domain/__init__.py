"""Pure domain layer.

No I/O, no framework, no database, no network, no model. Every module here is
a set of functions and value types that can be exercised with nothing but
pytest, which is what makes the rules in `CLAUDE.md` §6 testable in isolation.

Nothing in this package may import SQLAlchemy, FastAPI, psycopg, Alembic, or
any adapter. `tests/unit/test_layering.py` enforces that.
"""

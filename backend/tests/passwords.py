"""Password hashes for test fixtures."""

import functools

from app.auth.password import get_password_hash


@functools.lru_cache(maxsize=None)
def hashed_test_password(password: str) -> str:
    """The bcrypt hash of a fixture password, computed once per worker.

    `get_password_hash` runs bcrypt at the production cost (12 rounds, about
    a third of a second here), and `test_user` -- under every `client` -- used
    to pay it for every test. Any hash of a password verifies against it, so
    one per password is as real a credential as a fresh one: login still runs
    the production `verify_password` against a production-cost hash.

    `tests/unit/test_password.py` tests the hashing itself and keeps calling
    `get_password_hash` directly.
    """
    return get_password_hash(password)

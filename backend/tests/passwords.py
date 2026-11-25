"""Password hashes for test fixtures."""

import functools

import bcrypt

#: bcrypt's minimum cost. A hash records its own cost, so the production
#: `verify_password` checks it as it would any other -- in a fraction of the
#: time a production-cost (12 rounds) hash takes.
TEST_BCRYPT_ROUNDS = 4


@functools.lru_cache(maxsize=None)
def hashed_test_password(password: str) -> str:
    """A bcrypt hash of a fixture password, computed once per worker.

    `get_password_hash` runs bcrypt at the production cost (12 rounds, about
    a third of a second here), and `test_user` -- under every `client` -- used
    to pay it for every test, then again for each login that verified it.
    Any valid bcrypt hash of the password verifies against it, so a cheap one,
    shared per password, is as real a credential: login still goes through the
    production `verify_password`.

    `tests/unit/test_password.py` tests the hashing itself and keeps calling
    `get_password_hash` at its production cost.
    """
    salt = bcrypt.gensalt(rounds=TEST_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

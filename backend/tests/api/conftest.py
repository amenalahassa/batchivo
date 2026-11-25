"""The API suites' own configuration.

The role fixtures that used to live here -- ``as_role`` and
``make_user_with_role`` (task T034) -- have moved to ``tests/conftest.py``.
They were here on the grounds that only the HTTP suites needed a
differently-roled client; the settled-order integration suite now needs one
too, to prove that reading a realised margin is open to every role (FR-007c)
against the same settled sale the accuracy test reads. One definition, at the
root, rather than a second copy that would drift from it.

Nothing else was ever defined here. The file stays so that pytest keeps
treating ``tests/api`` as a package root for the suites below it.
"""

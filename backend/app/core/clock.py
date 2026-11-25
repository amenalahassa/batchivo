"""One authoritative notion of "today" and "now" (Constitution III).

The money paths had two. :mod:`app.services.pricing_policy` dated a policy row
from ``datetime.now(timezone.utc).date()`` while the endpoints that read it back
defaulted their ``as_of`` to ``date.today()`` — the *local* date of whatever
machine the process happened to run on.

Those agree for most of the day and disagree for the rest of it, which is the
worst possible failure shape:

* In UTC−4, between 20:00 and midnight local, the UTC date is already tomorrow.
  A policy written then is stamped with tomorrow's date, so every read defaulting
  to the local date finds **no policy in effect** and silently falls back to the
  legacy settings. An operator changes their labor rate in the evening, reloads,
  and sees the old figure with nothing to explain it.
* The same split reaches a price period (``valid_from``), a fee rule's
  effective date, an exchange rate's ``rate_date`` and a sale snapshot's
  reference date. A price written on one side of the boundary and read from the
  other is a price that does not exist yet.

So there is one function, and everything that dates a monetary record or reads
one as at a date calls it.

**It returns the UTC date.** Not because UTC is the operator's day — it is not
— but because every timestamp in this system is already stored in UTC, and a
record's ``created_at`` and its ``effective_from`` disagreeing is precisely the
bug above. Deriving the business date from the same clock as the timestamp
keeps them consistent by construction.

That does mean an operator in UTC−4 making a change at 21:00 sees it dated
tomorrow. That is a visible, explicable off-by-one rather than a silent
disappearance, and the honest fix is a per-tenant business timezone — which is
a product decision, not something to approximate with the server's locale.
When that arrives it belongs here, as one change, which is the other reason
this is a function rather than a call site.
"""

from datetime import date, datetime, timezone

__all__ = ["today", "now"]


def now() -> datetime:
    """The current instant, timezone-aware and in UTC."""
    return datetime.now(timezone.utc)


def today() -> date:
    """The current business date.

    Use this wherever a monetary record is dated or read as at a date — a
    policy period, a price period, a fee rule's effective range, an exchange
    rate's day, a sale snapshot's reference. Never ``date.today()``, which
    reads the server's locale and will not agree with the ``created_at`` of
    the row being written.
    """
    return now().date()

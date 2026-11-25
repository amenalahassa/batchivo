"""The literals several pricing resources share.

``MarginBasis`` had drifted into two definitions -- here and in
``pricing_policy.py`` -- which is how a basis a policy accepts comes to differ
from one a response can carry. It is defined once, here, and imported.

These are the vocabulary of the pricing API rather than a resource of their
own, so they live in a module named for what they are (task T138).
"""

from typing import Literal

#: What a fee is charged on (FR-021). The periodic bases at the end are
#: absorbed over a period rather than charged on an order (FR-025).
FeeBasis = Literal[
    "item_subtotal",
    "item_plus_shipping",
    "order_total",
    "per_listing",
    "per_order",
    "per_unit_sold",
    "per_month",
]

#: Which end of a clamp bound (FR-021c).
ClampApplied = Literal["min", "max"]

#: The denominator a margin percentage is taken over (FR-031b). A percentage
#: without its basis is a number two people will compare and disagree about.
MarginBasis = Literal["customer_total", "item_price", "net_revenue"]

#: Who hands the sales tax to the revenue authority (FR-028b).
TaxRemitter = Literal["marketplace", "operator"]


__all__ = ["ClampApplied", "FeeBasis", "MarginBasis", "TaxRemitter"]

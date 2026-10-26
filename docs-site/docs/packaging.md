---
sidebar_position: 3
title: Packaging & Parcels
---

# Packaging & Parcels

Batchivo knows how big each product is and which boxes you stock, so it can
suggest the box a product ships in, pack an order's items together, and price
postage from the parcel you actually send. This page explains where the
figures come from and what each screen does with them. For how postage feeds
a margin, see [How Pricing Works](./pricing-model.md#how-postage-is-worked-out).

## Dimensions

Every model, product and product variant can carry its size: length, width
and height in millimetres, to 0.1 mm. Each set of dimensions says where it came
from:

- **Measured** — read from an STL or 3MF file you uploaded.
- **Entered** — typed in by you.
- **Inherited** — a variant without its own size uses its product's.

### Measured from your files

When you upload an STL or 3MF to a model, Batchivo measures its bounding box.
A 3MF's units and transforms are applied, and Bambu Studio and OrcaSlicer
project files are read through their object parts. A file with several objects
lists each one's size, and the overall size is the build plate as laid out —
which may not be the assembled size, so check it.

The measurement fills in dimensions **only where there are none**: on the
model, and on a product made of exactly that one model at quantity 1. Once you
have entered dimensions, a new file only *offers* its measurement ("Measured
120.0 × 80.0 × 45.0 mm from dragon.3mf — Use these"); nothing you typed is
overwritten.

Files up to 25 MB are measured as they upload. Larger ones, up to 200 MB, are
measured in the background — the file shows "Measuring…" until it is done.
Files over 200 MB, and files that are not readable meshes, upload normally and
say why they were not measured.

## Packaging consumables

A consumable becomes packaging when you give it a **packaging kind**:

| Kind | What to record |
|------|----------------|
| Box | Inner length, width and height; wall thickness; empty weight |
| Mailer | Inner length and width, and its maximum thickness as the height; empty weight |
| Void fill | The volume one unit fills, in ml; its weight if you know it |
| Wrap | Nothing more |

A box or mailer without all three inner sizes is marked **Incomplete** in the
consumables list and is never suggested. Say whether the figures were
**measured** (with a ruler and scale) or **estimated** from a supplier listing;
the screens show which, as they do for every cost input.

## Suggesting a box

On a product, **Suggest packaging** ranks every box and mailer the item fits
in, keeping a clearance around it on every side:

1. boxes in stock before boxes out of stock;
2. then the smallest by volume;
3. then the cheapest.

Each suggestion shows how the item sits in it, the room left on each side, the
empty volume, and how much void fill would fill it. A product marked
**fragile** uses the larger fragile clearance and suggests wrap. The clearances
are set in **Settings → Pricing → Packaging** (10 mm and 20 mm until you change
them).

**Accept** sets that box as the product's packaging, which is what its cost
breakdown charges. The advisor never shows a cost of its own: the packaging
line in the cost breakdown is the only figure. If you later change the
product's size or the box's, and the box no longer fits, the product warns
you.

A variant can have its own size and its own packaging. If its packaging
differs from the product's, the variant says so: the cost breakdown still
charges the product's packaging.

## Size classes and volumetric weight

A shipping profile can carry **size limits** — the largest parcel the service
takes, all three sides or none — and a **volumetric divisor**. Size-limited
services are tried first, cheapest first; a parcel fits a size class whichever
way round it goes. With a divisor, the carrier charges the larger of the
actual weight and the volume weight.

## Packing an order

An order of several items is packed by the advisor: everything in one box if
one holds it, otherwise into as few boxes as hold it all. The order's
**packaging suggestions** list each parcel with its contents, outer size,
packed weight and void fill, and the postage they would cost — marked as an
**estimate**. An item without dimensions stops the suggestion and is named, so
you can add them.

## Confirming parcels at dispatch

**Mark as Shipped** first asks which parcels the order goes out in, starting
from the suggestion. Change the box or the void fill, add or remove a parcel,
then **Confirm parcels**. Confirming:

- records the parcels — once; they cannot be confirmed twice;
- takes the boxes and fill from stock, as shipping usage on the order (stock
  may go below zero, and you are told);
- sets the order's postage from those parcels, unless you entered the postage
  yourself.

You can **Skip** and ship without confirming; the postage then stays an
estimate.

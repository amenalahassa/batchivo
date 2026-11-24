---
sidebar_position: 5
title: Ideas
---

# Ideas

**Ideas** is where a product starts before it is a model: a problem you
noticed, a customer's request, a line from the monthly pain-point report. You
collect notes, links and pictures on it, score it, try it over a few
iterations, and when it is ready you turn it into a model or a product in one
step.

The Ideas page is on for every 3D-printing shop. For other shop types the
platform administrator can switch it on in the shop's modules.

## Who can do what

| Role | Can |
|------|-----|
| Viewer | Read ideas, their timeline and images |
| Member | Create, edit, archive and import ideas; add entries; convert to a model |
| Admin, owner | All of the above, and convert to a product |

Converting to a product needs the same role as creating a product on the
Products page. A member sees the button greyed out with the reason.

## Capturing an idea

**New idea** asks for a title; everything else is optional:

- **Summary** — markdown: the problem and the idea in a few lines.
- **Status** — Inbox, Exploring, Validating, Ready, Parked or Dropped. *Converted*
  is set only by a conversion; you can move a converted idea elsewhere and it
  keeps its links.
- **Source** and **source link** — your own idea, the pain-point report, a
  customer, or something else.
- **Tags** — comma separated, stored in lower case.
- **Scores** — five criteria from 1 to 5: frequency, frustration,
  printability, gap and willingness to pay.

### The score

When all five scores are set, the idea's score is their sum out of 25. When
some are missing the idea is shown as **Not scored** rather than as a low
total. An idea imported from the report carries the report's own total, shown
as **Report score 19/25**, until you set the five scores yourself; then your
total replaces it.

## Board and list

The **Board** has one column per status, each with its count, loading twenty
ideas at a time (**Load more** for the rest). Move a card with the menu under
it. The **List** searches title and summary, filters by status, tag, source and
archived state, and sorts by last update or score (ideas with no score last).

Archiving hides an idea from both. Choose **Archived** in the list filter to
find it again and **Restore** it.

## The timeline

Each idea keeps a timeline of entries, grouped by **iteration**, the latest
first; within an iteration, pinned entries come first, then the newest.

- **Note**, **Link**, **Measurement**, **Decision** — text in markdown.
- **Images** and **sketches** — JPEG, PNG or WebP up to 10 MB each, added with
  **Add images**, dropped on the composer, or pasted from the clipboard. Each
  refused file is listed with its reason; the others are kept.

**Start next iteration** opens a new round, with an optional note as its first
entry. Entries can be edited (they then show *edited*), pinned, and archived;
**Show archived** brings archived ones back into view.

The **star** on an image makes it the idea's **cover**, shown on the board
card. Archiving the cover clears it. The **Gallery** tab shows every image and
sketch of the idea with its iteration.

### Image privacy

Idea images are not public. They are shown only to a signed-in user of your
shop; anyone else gets nothing, and another shop is told the image does not
exist. Product images are unchanged and stay public on the shop.

## Converting an idea

- **Convert to model** makes a model from the idea: its title as the name, its
  summary as the description, its cover as the image. You can change the name
  and the reference first.
- **Convert to product** makes a product through the same creation as the
  Products page, with the idea's model as its bill of materials (quantity 1).
  If the idea was already converted to a model, that model is reused;
  otherwise one is made first. The cover and the pinned images are copied to
  the product, the cover first as its main picture, unless you untick **Copy
  the cover and pinned images**.

A conversion is all or nothing: if any step fails, no model, product or
image is left behind and the idea is unchanged. Afterwards the idea is
**Converted** and links to what it became, and the model and product pages
show **From idea** with a link back. An idea converted to a product cannot be
converted again. If the model or product is deleted later, the idea stays and
shows the link as *no longer exists*.

## Importing the pain-point report

**Import report** takes the monthly pain-point report: paste it, or drop or
pick its `.md` file. **Preview** reads every problem in it — title, report
score, niche as a tag, the first evidence link — and shows what would be
created, what was already imported, and what is refused, without writing
anything. **Import** then creates the new ones in the Inbox with the source
*Pain-point report*.

A problem whose evidence link matches an idea already imported from that link
is skipped, even if that idea was archived or converted, so importing the same
report twice creates nothing the second time. An invalid problem is refused on
its own; the rest are imported.

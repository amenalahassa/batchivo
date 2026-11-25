---
sidebar_position: 4
title: Model Files & Versions
---

# Model Files & Versions

A model can hold any number of files: the part itself (an `.stl` or a project
`.3mf`) and the sliced plates you print from (`.gcode` or a Bambu/Orca
`.gcode.3mf`). Files are grouped into **versions**, so you keep every revision
of a design with a note on what changed, and you choose which version is used
for printing.

## Source files and sliced files

| File | What it holds | What Batchivo reads from it |
|------|---------------|-----------------------------|
| `.stl` | The part's shape | Its dimensions |
| Project `.3mf` (Bambu Studio: **File → Save project**) | The part's shape, and often its plate settings | Its dimensions |
| `.gcode` | The print, sliced | Print time and filament weight |
| `.gcode.3mf` (Bambu Studio: **Export plate sliced file**) | The print, sliced, one G-code per plate | Print time, the objects on each plate, and the grams of each filament |

A sliced file holds the print, not the part's shape, so it **cannot be
measured**. If you upload only a `.gcode.3mf`, the files card says so and asks
for the project `.3mf` or the `.stl`. Upload both to the same version: one
gives the dimensions, the other the print figures.

You can attach a source file when you create or edit a model ("Source file
(.stl or project .3mf)"). The file you use for **Auto-fill from .3mf** is kept
on the model too, unless you untick **Keep this file on the model**.

A measurement never overwrites dimensions you typed: it is offered for you to
adopt, and the figure you adopt is recorded as *measured*.

## Versions

- The first file of a model makes **version 1**, which is active.
- When you upload, choose **New version…** to start a new version and say
  what changed ("thicker walls", "fixed the handle overhang"). Leave the
  version picker on the active version to add a file to it.
- A new version is **not active** until you make it active. Right after the
  upload, Batchivo offers **Make active**.
- Versions are listed newest first, with their note, date and who created
  them. Any of them can be downloaded or made active again.

### The print file

Each version has one **print file**: the sliced file whose print time, plate
count and filament weight describe the print. The first sliced file you upload
to a version becomes its print file; use **Use as print file** (the printer
icon) to pick another.

Only the active version's print file feeds the cost profile. Its dimensions
come from the version's measured source file.

## Making a version active

Making a version active, or changing the active version's print file, opens a
review. It lists every figure that would change, the current value and the new
one:

- **Plate print time** and **Items per plate**, from the print file. All the
  file's plates are one print run: their times are added together, and the
  items per plate are the **objects** the plates print, not the number of
  plates. Two plates with four copies each make 8 items; a body on one plate
  and its base on another make 2 objects, so check the figure (see below).
  When the file does not list its objects, the row says so and keeps the
  current figure.
- **Filament weight**, on the bill of materials (or on the planned printer's
  settings, when the model has them, divided by the items). When the model
  has several materials, each line gets the grams of its own filament,
  matched on material and colour ("PLA Red 60 g, PLA Black 24 g"). If a line
  has no single matching filament in the file, or the file uses a filament no
  line has, the row names what did not match and cannot be taken.
- **Dimensions**, from the measured file, named in the review.

Tick the figures to take, untick the ones to keep. Nothing changes that you did
not tick. A figure that cannot be taken says why, for example when the file
does not give grams per filament for a model with several materials.

### Auto-fill on the model form

**Auto-fill from .3mf** reads the same figures. After choosing the plates it
asks **How many finished items do these plates make?**, filled with the
objects on the chosen plates and editable: change it when several objects
make one item. It shows what one item takes (time and grams) before you
apply. The filament weight is offered on the bill-of-materials step; a file
with several filaments lists each one there, so you add one line per colour.

Bill-of-materials grams are for the **whole plate run**: the cost divides
them by Items per plate.

Figures you take are recorded as *measured* from the file. **Orders already
placed keep the cost they were placed at**: making another version active
changes the cost of what you make next, never the history.

## Deleting files

- The **active version's only file** can't be deleted: make another version
  active first.
- The **active version's print file** can't be deleted: choose another print
  file, or make another version active.
- Deleting an inactive version's print file makes its newest other sliced file
  the print file. A version left without files is removed, unless it still has
  notes.
- A deleted file's notes are **archived**, not lost. Turn on **Archived** in
  the notes list to see them.

## The 3D viewer

Every uploaded file opens in the viewer (the eye icon):

- a part as a solid you can turn and zoom;
- a sliced file as its toolpaths, with a **Layer** slider; a multi-plate
  `.gcode.3mf` has a **Plate** picker.

When the model has a planned printer (set in the cost profile), its bed is
drawn at true size, so a part that is off the bed or too large shows at once.
When a sliced file says it was made for another printer, filament or nozzle
than the plan, the viewer says so.

Large files stay usable: they are read in the background, and above 50 MB only
part of the lines or triangles is drawn, with the note "Reduced preview".

Files linked from a path on your computer (**Link Local File**) are not
uploaded, so they can't be opened in the viewer.

## Notes on the part

In the viewer, choose **Add note** and click a point on the part (or on the
current layer of a sliced file) to pin a numbered note there. Hover a pin to
read it. Notes are also listed beside the viewer, with a status filter, so you
can read them on a phone without the 3D view.

When you open a file of a newer version, the earlier versions' open notes show
as faded pins at the same place. For each one:

- **Resolved in this version** closes it;
- **Carry forward** makes a new note on this version, linked to the original,
  which you can **Move** onto the reshaped part. The original stays where it
  was and reads *Carried forward*.

That is where to leave "next version" notes: pin them on the current version,
and deal with them when the next one is uploaded.

## Who can do what

Members, admins and owners upload, make versions active, choose print files,
delete files and write notes. Viewers can open, download and read everything,
notes included, but see no buttons that change anything.

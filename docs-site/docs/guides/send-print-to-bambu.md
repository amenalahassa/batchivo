---
sidebar_position: 6
---

# Send a print to a Bambu Lab printer

Start a sliced plate on a Bambu Lab printer on your network, after checking a
summary of what is about to print.

## Before you start

- The printer and Batchivo's server are on the same network.
- **Developer Mode is on on the printer** (printer screen → Settings → LAN only
  mode → Developer Mode). Developer Mode lets Batchivo send files and start
  prints, but **it turns off Bambu cloud access**: Bambu Handy and cloud
  printing stop working on that printer. If you need the cloud, keep sending
  from Bambu Studio or Bambu Connect instead.
- The file is **sliced**: a `.gcode.3mf` exported from Bambu Studio or Orca
  Slicer. A project file that has not been sliced cannot be sent.

## Set up the printer

1. Go to **Printers** and click **Connection** on the printer's row.
2. Enter the serial number, the IP address and the access code shown on the
   printer screen. The access code is never shown back; leave the field blank
   later to keep the stored one.
3. Turn on **Developer Mode is on on this printer** once you have switched it on
   on the printer itself.
4. Optionally click **Test file transfer**. It logs in to the printer's file
   server and writes nothing. A failed test does not stop you saving.
5. Click **Save**. The **Send print** button now appears on the printer's row.

## Send a print

1. Click **Send print** on the printer's row.
2. Choose the file: upload a `.gcode.3mf` (optionally keeping it on a model), or
   pick a sliced file already stored on a model.
3. Choose the plate, then the AMS slot (or the external spool) for each
   filament the plate uses.
4. Click **Prepare**. Batchivo shows the summary: printer, file, plate, print
   time, weight, and for each filament the slot, the spool Batchivo has
   there and what the printer reports.
5. Read the warnings. A different material or colour, an empty slot or a slot
   with no known spool is flagged. If there are warnings, tick
   **I have checked the warnings**.
6. Click **Start print** within five minutes. After that the summary expires
   and you prepare again.

Nothing reaches the printer until you click **Start print**. The print job is
created only once the printer has accepted the start command. If the printer
is busy or cannot be reached, **Start print** stays disabled.

## After the print: deduct the filament

When a print sent from Batchivo finishes, the printer's **Sends** list shows a
proposed deduction for each spool used, from the sliced weights. Correct a
weight if needed, untick a line to leave that spool alone, then **Accept
deduction** — or **Dismiss** it. Nothing is deducted until you accept.

Each accepted line is recorded as a usage transaction on the spool, linked to
the print job.

## Who can send

Any member of the workspace (role Member or above) can prepare and confirm a
send. Viewers cannot.

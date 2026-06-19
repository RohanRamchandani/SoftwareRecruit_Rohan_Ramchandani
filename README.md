# Software Recruitment Package — Rohan Ramchandani

This repository contains my submissions for the TMR software recruitment tasks.
It is split into two self-contained projects, each in its own folder with its
own detailed README.

## Projects

### `UDP_Communication/`
Sends an array of 100 sixteen-bit integers from one computer to others on a
local network over a UDP socket. Includes a sender and a receiver, with
run-length encoding to handle repeated values and validation on both ends.

**Tools:** Python (standard `socket` module).

### `PyQT_GUI/`
A desktop app that displays two live video feeds at once. A single camera is
captured and split into two identical streams shown side by side, with controls
for start/stop, source selection, snapshots, and a live FPS readout.

**Tools:** Python, PyQt5, GStreamer.

## More detail

Each folder's own `README.md` covers how to run that project, the design
choices behind it, and how the code works.

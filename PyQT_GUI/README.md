# Dual Camera Feed — PyQt5 + GStreamer

Camera Systems task for the TMR software recruitment package.

A PyQt5 desktop app that shows **two live video feeds at once**. It grabs a
single camera, and uses GStreamer to split that one stream into two identical
copies, which are drawn side by side in the window. So you see two feeds, but
there's only ever one real camera running underneath — the "duplicated live
stream" approach the brief recommends. It proves simultaneous video works
without needing two physical cameras.

The window is two equal video panes side by side, each with a title and a live
FPS readout, and a control bar underneath (source selector, Start, Stop,
Snapshot) plus a status bar along the bottom.

---

## Requirements coverage

| Requirement | How it's met |
|---|---|
| GUI built with PyQt | Pure PyQt5 — window, panes, buttons, and layouts. |
| Both feeds in a clear, intentional layout | Two equal labelled panes side by side, with a control bar and status bar below. |
| A working video stream | Live webcam via GStreamer, shown in both panes; a no-hardware test pattern is also included. |
| Document the development process | Section 1. |
| Explain how the code runs | Sections 3 and 4. |
| Reasoning behind the design and features | Sections 2, 4, and 5. |
| Well-commented code | Every class, method, and tricky line is commented in `camera_gui.py`. |
| Duplicated live stream (recommended) | A GStreamer `tee` clones one capture into two feeds. |
| What I'd build next | Section 6. |

---

## Project files

| File | Purpose |
|---|---|
| `camera_gui.py` | The whole app, in one commented file. |
| `environment.yml` | The exact conda environment, so it's reproducible. |
| `README.md` | This document. |

---

## 1. Development process

I worked in four steps:

1. **Checked the environment first.** Before writing anything I looked at what
   was installed. GStreamer's command-line tools were there, but its Python
   bindings, OpenCV, and Qt were not. That told me the real work was setting up
   a correct toolchain, and it shaped the backend choice in Section 2.
2. **Picked the backend and isolated it.** I went with GStreamer (the team's
   stack) and put it in a dedicated conda environment, so my base install stayed
   clean and the project stays reproducible for whoever runs it.
3. **Built the video path before the GUI.** The hard part is getting frames out
   of GStreamer and safely onto PyQt's thread, so I solved that first (Section
   4.2), then built the window around it.
4. **Tested, then documented.** I verified the frame path with an automated
   headless test (Section 5) before writing this.

---

## 2. Why GStreamer

The brief recommends GStreamer because it's what the Camera Systems team uses,
and allows an alternative only if it's clearly justified. I chose GStreamer so
my code lives in the same world the team works in. The split is simple:

- **GStreamer** does the video — grabbing frames, fixing the colour format, and
  splitting the stream into two.
- **PyQt5** does everything you see — the window, the buttons, and drawing each
  frame.

The only catch was that GStreamer's Python bindings and some plugins weren't
installed, and the default Python had no Qt. Rather than touch my base setup, I
built an isolated conda environment with a known-good toolchain. `environment.yml`
recreates it exactly. The key versions: Python 3.12, GStreamer 1.28, PyQt5
5.15.2, and PyGObject (the bridge that lets Python drive GStreamer).

---

## 3. How to run it

### One-time setup

```
conda env create -f environment.yml
```

### Run

```
conda activate camerafeed
cd PyQT_GUI
python camera_gui.py
```

Then pick a **Source** and press **Start**:

- **Webcam** — the live camera. macOS asks for camera permission the first time;
  allow it (System Settings, then Privacy & Security, then Camera).
- **Test pattern** — a moving pattern GStreamer makes itself. No camera or
  permission needed; handy for a quick check or a machine with no camera.

---

## 4. How the code works

`camera_gui.py` is one file in four commented sections: the GStreamer side, one
video pane, the main window, and the entry point.

### 4.1 The pipeline — one camera, two feeds

GStreamer builds the whole video path from a single text recipe. In plain terms
it reads: grab the camera, normalise the format, resize to 640x480 RGB, then
split. The split is the important part:

```
camera  ->  convert  ->  resize to 640x480 RGB  ->  tee
                                                      |-> queue -> appsink (left pane)
                                                      |-> queue -> appsink (right pane)
```

- **`tee`** is the core idea — it clones every frame down both branches. This is
  better than opening the camera twice, since most cameras allow only one
  consumer, and grabbing once is cheaper.
- **`queue`** on each branch gives each feed its own small buffer on its own
  thread, so if one feed stutters it can't drag the other down.
- **`appsink`** is the exit door out of GStreamer — instead of drawing the video
  itself, it hands each frame back to Python. It's set to keep only the newest
  frame and drop old ones, so if the GUI ever falls behind there's no growing
  lag. For live video, the newest frame matters more than every frame.
- Choosing the test pattern just swaps the camera source for `videotestsrc`;
  everything after the split is identical.

### 4.2 Getting frames into PyQt — the threading part

This is the only subtle bit. GStreamer hands us each frame from its own
background threads, but PyQt only lets you touch the window from its own thread.
So the rule is:

1. On GStreamer's thread, do the bare minimum: copy the frame into a `QImage`
   (a private copy, since GStreamer reuses its buffer immediately), then emit a
   PyQt signal carrying it. No window code runs here.
2. PyQt delivers that signal to the main thread — its built-in, safe way to pass
   data between threads.
3. On the main thread, the pane scales the image to fit (keeping its proportions)
   and draws it.

Forcing capture to 640x480 RGB keeps this clean: each row is exactly 1920 bytes
with no padding, so PyQt reads the raw pixels correctly with no alignment maths.

### 4.3 The window — `VideoPane` and `MainWindow`

- **`VideoPane`** is one feed's display: a title, the video, and a live FPS
  count. It's written once and used twice, so both feeds are identical and
  there's no copy-pasted code.
- **`MainWindow`** puts the two panes side by side, adds the controls and status
  bar, and connects the pipeline's signals to the panes.

### 4.4 Errors and cleanup

GStreamer reports problems (like denied camera access) on a message bus. A timer
checks that bus ten times a second and, on an error, shows it in the status bar
and resets the buttons — so a failure is visible, not a silent freeze. The camera
is always released on Stop and when the window closes.

---

## 5. Features, and why each one is there

Each feature earns its place rather than being decoration:

| Feature | Why |
|---|---|
| Two side-by-side panes | The core requirement — shows two feeds running at once. |
| Source selector (Webcam / Test pattern) | Runs on any machine and gives a fallback when there's no camera; also makes the app testable with no hardware. |
| Start / Stop | Direct control of the camera; Stop actually releases it. |
| Live FPS per feed | Honest, instant proof both feeds are live and keeping up. |
| Snapshot both | Saves a still from each feed at once — a common camera-tool action. |
| Status bar with errors shown | You're never left guessing why video stopped. |
| Aspect-ratio-preserving scaling | The picture never stretches when you resize the window. |

---

## 6. Verification

I checked the frame path with an automated headless test, using the test pattern:

- both feeds delivered about 74 frames over 2.5 seconds (~30 fps), confirming the
  `tee` drives both outputs at full rate;
- every frame arrived as a 640x480 RGB image;
- a full Start then Stop cycle ran cleanly and released the pipeline.

The webcam needs interactive camera permission, so it's verified by running the
app normally (Source: Webcam, then Start).

---

## 7. What I'd build next

- **Different effect per feed** — give the second branch its own GStreamer effect
  (e.g. grayscale or edge-detect) so the panes do visibly different work, not
  just a copy. The `tee` setup already allows adding elements to one branch only.
- **Networked H.264 feeds** — match the team's real setup by encoding to H.264
  and streaming over the network, decoding in the GUI. This build's GStreamer was
  missing the H.264 plugins, so I kept the demo to raw video; only the source
  would change.
- **Six feeds** — the team's production scale. The same pane + `tee`/`appsink`
  pattern extends straight to a 2x3 grid.
- **Record to disk** per feed.

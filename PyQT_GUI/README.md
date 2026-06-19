# Dual Camera Feed — PyQt5 + GStreamer

Camera Systems task for the TMR software recruitment package.

A PyQt5 desktop GUI that displays **two concurrent video feeds**. A single live
camera is captured once and duplicated inside a GStreamer pipeline, so both
panes show the same live source running simultaneously — the "duplicated live
stream" approach the task recommends.

![layout](layout-not-included) <!-- placeholder: the running window is two equal
video panes side by side, with a control bar underneath. -->

```
┌───────────────────────────────┬───────────────────────────────┐
│        Feed 1  (live)         │      Feed 2  (duplicated)     │
│   ┌───────────────────────┐   │   ┌───────────────────────┐   │
│   │      live video       │   │   │      live video       │   │
│   └───────────────────────┘   │   └───────────────────────┘   │
│           FPS: 30             │           FPS: 30             │
├───────────────────────────────┴───────────────────────────────┤
│ Source: [Webcam ▾] [Start] [Stop] [Snapshot both]             │
├────────────────────────────────────────────────────────────────┤
│ Streaming…                                                     │  status bar
└────────────────────────────────────────────────────────────────┘
```

---

## 1. Why GStreamer (and how I set it up)

The task recommends GStreamer because that's what the Camera Systems team uses,
so I built directly on it rather than on a higher-level alternative. GStreamer
does the video work (capture, colour conversion, splitting the stream); PyQt5
does the GUI (layout, controls, drawing the frames).

The one wrinkle: GStreamer was on my machine, but its **Python bindings**
(`PyGObject` / the `gi` module) and several plugins were not, and the system
Python had no Qt at all. Rather than disturb my base environment I created an
**isolated conda environment** that pins a known-good stack. This is also why
the project is reproducible — the exact toolchain is captured below.

| Component        | Version    | Role                                   |
|------------------|------------|----------------------------------------|
| Python           | 3.12       | runtime                                |
| GStreamer        | 1.28       | capture / convert / split video        |
| PyGObject (`gi`) | conda-forge| lets Python drive GStreamer            |
| PyQt5            | 5.15.2     | the GUI                                |

---

## 2. How to run it

### One-time setup (creates the isolated environment)

```bash
conda create -y -n camerafeed -c conda-forge \
    python=3.12 pygobject gst-python \
    gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad \
    pyqt numpy
```

`gst-plugins-bad` is included because the macOS camera source
(`avfvideosrc`, from Apple's AVFoundation) ships in that plugin set.

### Each time you run it

```bash
conda activate camerafeed
cd PyQT_GUI
python camera_gui.py
```

Then in the window: pick a **Source**, press **Start**. With *Webcam* selected,
macOS will ask for camera permission the first time — allow it. If you have no
camera or are running over SSH, choose **Test pattern (videotestsrc)**, which
needs no hardware and is what I used for automated testing.

> Note: the **Test pattern** source always works with zero setup. The **Webcam**
> source needs camera permission granted to your terminal app
> (System Settings → Privacy & Security → Camera).

---

## 3. How the code works

The whole program is one file, `camera_gui.py`, in four clearly-commented
sections. Here is the design at a glance.

### 3.1 The GStreamer pipeline — one source, two feeds

```
avfvideosrc                      capture the camera once
  ! videoconvert ! videoscale    normalise format and size
  ! video/x-raw,format=RGB,640x480
  ! tee name=t                   *** SPLIT into two identical streams ***
      t. ! queue ! appsink sink0     branch 1 → Python → left pane
      t. ! queue ! appsink sink1     branch 2 → Python → right pane
```

* **`tee`** is what makes this "two concurrent feeds" from one camera: it
  duplicates every frame down both branches. This is deliberately better than
  opening the camera twice — most cameras can only be opened by one consumer,
  and capturing once is cheaper.
* **`queue`** on each branch decouples the two feeds so a hiccup in one can't
  stall the other (each `queue` runs its branch on its own thread).
* **`appsink`** is the bridge out of GStreamer: instead of drawing the video
  itself, it hands each raw frame back to Python. It's configured with
  `max-buffers=1 drop=true` so that if the GUI ever falls behind, GStreamer
  drops stale frames rather than building up latency — the right trade-off for
  *live* video, where the newest frame matters more than every frame.
* Switching the Source dropdown to the test pattern simply swaps
  `avfvideosrc` for `videotestsrc`; everything downstream is identical.

### 3.2 Getting frames from GStreamer into Qt (the threading model)

This is the only subtle part, and the code is heavily commented around it.

GStreamer calls our `appsink` callback on **its own streaming threads**, not on
Qt's GUI thread. Touching a Qt widget from another thread is undefined
behaviour, so the rule is strict:

1. **On the GStreamer thread** (`CameraPipeline._on_sample`): map the frame's
   bytes, wrap them in a `QImage`, and immediately `.copy()` so we own the
   memory (GStreamer frees its buffer the moment we unmap). Then `emit` a Qt
   signal carrying that QImage. *No widget is touched here.*
2. **Qt delivers the signal to the GUI thread** as a queued event — the
   supported, thread-safe way to move data between threads.
3. **On the GUI thread** (`VideoPane.update_frame`): scale the image to the
   pane (preserving aspect ratio) and draw it.

Forcing the capture to 640×480 RGB keeps this conversion trivial: each row is
exactly `640 × 3 = 1920` bytes with no padding, so the `QImage` reads the bytes
correctly with no stride surprises.

### 3.3 The GUI (`VideoPane` and `MainWindow`)

* **`VideoPane`** is a reusable widget: a title, the video image, and a live
  FPS read-out. Writing it once and instantiating it twice keeps the two feeds
  guaranteed-identical and the code DRY.
* **`MainWindow`** lays the two panes out side by side (the "structured,
  intentional layout"), adds the control bar, and wires the pipeline's signals
  to the panes.

### 3.4 Error handling

GStreamer reports problems (e.g. camera permission denied) asynchronously on a
*message bus*. A `QTimer` polls that bus 10×/second from the GUI thread and, on
an error, shows it in the status bar and resets the controls — so a failure is
visible and recoverable instead of a silent freeze or a crash. The camera is
always released on **Stop** and on window close (`set_state(NULL)`).

---

## 4. Features, and why each one earns its place

The task asks for functionality that genuinely makes sense, so every feature is
justified rather than decorative:

| Feature | Why it's there |
|---|---|
| **Two side-by-side panes** | The core requirement: prove two feeds run at once. |
| **Source selector (Webcam / Test pattern)** | Makes the app runnable on *any* machine — graceful fallback when no camera or permission. This is also what makes the project testable in CI / headless. |
| **Start / Stop** | Explicit control over the camera; Stop actually frees the device. |
| **Live FPS per feed** | Immediate, honest feedback that both feeds are truly live and keeping up — the most useful single diagnostic for a video system. |
| **Snapshot both** | Capture a synchronised still from each feed; a real, common operation for camera tooling. |
| **Status bar + bus error surfacing** | Operators should never be left guessing why video stopped. |
| **Aspect-ratio-preserving scaling** | The picture never distorts when the window is resized. |

---

## 5. Verification

The frame path was validated automatically with a headless smoke test
(`QT_QPA_PLATFORM=offscreen`, test-pattern source):

* both feeds delivered ~74 frames over 2.5 s (≈30 fps), confirming the `tee`
  truly drives two independent appsinks at full rate;
* every frame arrived as a 640×480 `QImage` in `Format_RGB888`;
* a full `MainWindow` Start→Stop cycle ran cleanly and released the pipeline.

The webcam source additionally requires interactive camera permission, so it is
verified by running the app normally (Source → Webcam → Start).

---

## 6. What I'd build next (intended, not yet implemented)

Documenting intent, as the task invites:

* **Per-feed processing** — give the second branch a distinct GStreamer effect
  (grayscale / edge-detect via `videobalance` or `edgetv`) to show the panes
  doing genuinely different work, not just duplication. The `tee` architecture
  already supports adding elements on one branch only.
* **Networked H.264 feeds** — match the team's real setup by encoding with
  `x264enc` and sending over the network with `rtph264pay`/`udpsink`, decoding
  in the GUI. (This build's GStreamer was missing the H.264 plugins, so I kept
  the demo to raw video; the architecture is unchanged — only the source branch
  differs.)
* **Six feeds** — the team's production setup. The `VideoPane` + `tee`/appsink
  pattern scales directly: a 2×3 grid of panes with one appsink each.
* **Record-to-disk** per feed (`filesink` branch off the `tee`).
```

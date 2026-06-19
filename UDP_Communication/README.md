# UDP Communication

Mandatory task for the TMR software recruitment package.

The job: send an array of 100 sixteen-bit integers from one computer to 20 computers
on a local network, over a UDP socket. There are two scripts — `sender.py` builds the
array and transmits it, and `receiver.py` simulates one of the 20 machines that receives
and prints it back.

I'm only allowed to use the standard `socket` module for the actual sending and
receiving. I do use `struct`-style byte conversion (`to_bytes` / `from_bytes`) for
turning integers into bytes, but that's data formatting, not networking — the socket
itself only ever does `sendto` and `recvfrom`.

## How to run it

Open two terminals. Start the receiver first so it's listening before anything is sent:

```
python receiver.py      # terminal 1 — sits and waits
python sender.py        # terminal 2 — sends once, then exits
```

Both default to `127.0.0.1` (localhost) so you can test the whole thing on one machine
with no network involved. The receiver should print the same integers the sender printed.

## How the two scripts are connected

There is no real "connection" here, and that's on purpose. UDP doesn't do a handshake —
the sender never checks if the receiver is alive, it just throws a packet at an address
and forgets about it. The receiver just sits on `recvfrom` and catches whatever lands.

So the only thing that links the two scripts is a set of rules they both agree on ahead
of time and both hardcode:

- same **port** (5555),
- same **byte format** (described below),
- same **SIGNED** setting (so they interpret the numbers the same way).

They never talk to each other to set this up — they just both follow the same layout.
That shared format *is* the connection. (TCP would do a real handshake and guarantee
delivery; I went with UDP because the task asked for it, and because it supports
broadcasting, which I needed for the "single transmission" part.)

## Turning the integers into bytes

A socket can only send bytes, not Python integers, so every number has to be converted
first. One byte only holds 0–255, which is too small for values up to 65535, so each
16-bit integer needs **2 bytes**.

The way I think about this is just base conversion. A byte is base-256 (it holds 256
different values), so splitting a number into bytes is the same repeated-division trick
as converting to any other base — you just divide by 256. For example, 700:

```
700 ÷ 256 = 2 remainder 188   →   bytes [2, 188]   (because 2×256 + 188 = 700)
```

The quotient is the first byte, the remainder is the second. base-256 is the natural base
for this because one digit lines up with exactly one byte — no leftover bits.

Everything is sent **big-endian** ("network byte order"), which just means the bigger part
of the number comes first, like how we write 700 with the hundreds digit first. The actual
order doesn't matter as long as both sides agree, and big-endian is the standard convention
for networking, so the sender and receiver have an obvious shared rule to follow. (Side
note: the I2C task in this same package mentions the Teensy stores data little-endian —
endianness is a choice, I just picked the networking convention here.)

The receiver does the exact reverse with `from_bytes`, same "big" order, to rebuild the
integers.

## Wire format

```
HEADER (4 bytes)
  [ count    : 2 bytes ]   how many integers in total
  [ checksum : 2 bytes ]   sum of all values, mod 65536

BODY (4 bytes per run)
  [ value : 2 bytes ][ run length : 2 bytes ]   repeated until the array is covered
```

## Run-length encoding (handling long runs of the same value)

The task says to handle long sequences of the same integer. The naive approach sends the
value over and over — ninety 7s would be 180 bytes of the same thing. Instead I collapse
each run of identical values into a single `(value, count)` pair, no matter how long the
run is. So `[7, 7, 7, ...]` ninety times becomes just `(7, 90)` — 4 bytes instead of 180.
The receiver expands it back (`[7] * 90`) to get the original array.

The honest trade-off: RLE only helps when there are actual runs. If the array is fully
random with no repeats, every value becomes its own run of length 1, so each value drags
a useless count along with it and the packet ends up *bigger* than just sending raw
(20 bytes vs 10 for five random values). That's not a bug, it's the nature of RLE — it
shrinks repetitive data and bloats random data. For this use case (which is likely to have
runs) I think it's the right call, but it's a deliberate choice, not a free win.

## Reaching all 20 computers in one transmission

I don't actually send to all 20 individually. I send **once** to the broadcast address
`192.168.1.255`, and the network hardware copies the packet to every machine on the subnet.
That's the "single transmission" requirement — one `sendto` call instead of a loop of 20.

`192.168.1.255` isn't a real computer — it's the reserved "everyone on this subnet" address.
It comes from the subnet mask `255.255.255.0`, which says the first three numbers identify
the network and the last number identifies the machine. The highest value in that last slot
(`.255`) is reserved to mean "all hosts."

Two things worth knowing about how this is bounded:

- The OS blocks broadcasting by default (a packet hitting every machine is something you
  should only do on purpose), so I have to enable it explicitly with
  `setsockopt(SOL_SOCKET, SO_BROADCAST, 1)`. That flag is harmless when sending to
  localhost, so I can leave it on in both modes.
- Broadcast doesn't "stop at 20" — it stops at the **subnet boundary**. A router won't
  forward broadcast packets out of the local subnet, so it can't leak onto other networks
  or the internet. The 20 computers just happen to be everyone inside that boundary. If a
  21st machine were on the same subnet it would get the packet too — broadcast means
  "everyone here," not "these specific 20." For this task that's fine, but it's the reason
  broadcast is a blunt tool.

## Data validation

Because UDP guarantees nothing — packets can be dropped, arrive out of order, or get
corrupted — the receiver can't just trust what it gets. I validate on both ends:

- The sender checks the array before sending: exactly 100 values, all integers, all inside
  the 16-bit range. Bad data gets caught on my machine instead of going out on the wire.
- The header carries a **count** and a **checksum** (the sum of all values, low 16 bits).
  The receiver re-counts and re-sums what it decoded and compares. If even one value got
  corrupted in transit, the sums won't match and the packet is rejected. It also checks
  there are no leftover bytes, which would mean a malformed packet.

If a packet fails any check, the receiver prints a warning and goes back to listening
instead of crashing — a listener shouldn't die because one bad packet showed up.

## Re-homing the receiver onto a real machine

The receiver's IP is a global variable (`RECEIVER_IP`) at the top of the file so the script
is trivial to move onto any of the 20 machines — you just change that one line to that
machine's own address, or set it to `""` to listen on every interface (which is what you
need to actually catch a broadcast). The sender's `TARGET_IP` is global for the same reason:
flip it from `127.0.0.1` to `192.168.1.255` and the same single `sendto` now reaches the
whole network, no other changes.

## Signed vs unsigned

The task didn't specify, so I made it a switch (`SIGNED`). With `SIGNED = True`, values run
-32768..32767 (two's complement); with `False`, 0..65535. Both are valid uses of 16 bits —
it just changes how the top bit is interpreted. The sender and receiver both have to use the
same setting or negative numbers come out wrong.

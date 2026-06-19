"""
reciever.py
-----------
Listens for UDP datagrams from sender.py, rebuilds the integer array,
validates it, and prints it. (Simulates one of the 20 receivers.)

To re-home this script onto a real machine, change RECEIVER_IP to that
machine's own address (e.g. "192.168.1.7"), or set it to "" to listen on
every network interface -- which is what you need to catch a broadcast.
For local testing keep "127.0.0.1".
"""

import socket

# ---------------------------------------------------------------------------
# Configuration  (the IP lives in a global so this file is trivial to re-home)
# ---------------------------------------------------------------------------
RECEIVER_IP = "127.0.0.1"   # "" -> listen on all interfaces (needed for broadcast)
PORT        = 5555
BUFFER_SIZE = 1024          # max datagram we read; our packet is <= 404 bytes
SIGNED      = False          # MUST match the sender's SIGNED setting


def decode(data):
    """Reverse of sender.encode(): bytes -> list of integers, with checks."""
    if len(data) < 4:
        raise ValueError("packet too short to contain a header")

    count    = int.from_bytes(data[0:2], "big", signed=False)
    checksum = int.from_bytes(data[2:4], "big", signed=False)

    values = []
    offset = 4
    while offset + 4 <= len(data):
        v   = int.from_bytes(data[offset:offset + 2], "big", signed=SIGNED)
        run = int.from_bytes(data[offset + 2:offset + 4], "big", signed=False)
        values.extend([v] * run)        # expand the run back to full length
        offset += 4

    # ---- data validation -------------------------------------------------
    if offset != len(data):
        raise ValueError("trailing bytes: packet is malformed")
    if len(values) != count:
        raise ValueError(
            f"length mismatch: header said {count}, decoded {len(values)}"
        )
    if (sum(values) & 0xFFFF) != checksum:
        raise ValueError("checksum mismatch: data was corrupted in transit")

    return values


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((RECEIVER_IP, PORT))
    print(f"Listening on {RECEIVER_IP or 'all interfaces'}:{PORT} ...")

    while True:
        data, sender = sock.recvfrom(BUFFER_SIZE)
        try:
            values = decode(data)
        except ValueError as err:
            print(f"Dropped bad packet from {sender}: {err}")
            continue

        print(f"\nReceived {len(values)} integers "
              f"({len(data)} bytes) from {sender}:")
        print(values)


if __name__ == "__main__":
    main()

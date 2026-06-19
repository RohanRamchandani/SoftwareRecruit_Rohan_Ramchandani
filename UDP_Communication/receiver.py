import socket

# Configuration  (the IP lives in a global so this file is trivial to re-home)
RECEIVER_IP = "127.0.0.1"   # Listen on all interfaces (needed for broadcast)
PORT        = 5555
BUFFER_SIZE = 1024          # Max datagram we read; our packet is <= 404 bytes
SIGNED      = False          # Must match the sender's SIGNED setting


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
        values.extend([v] * run)        # Expand the run back to full length
        offset += 4

    # Data Validation
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

import socket
import random


# Configuration  (edit these to move the program between machines / networks)
TARGET_IP = "127.0.0.1"     # "192.168.1.255" to broadcast to the whole subnet
PORT      = 5555
ARRAY_LEN = 100             # How many integers we promise to send
SIGNED    = False            # True  -> values in -32768 .. 32767  (two's complement)
                            # False -> values in 0 .. 65535
                            # (the receiver's SIGNED must match this!)

# The legal range for one 16-bit value, derived straight from the bit math:
# 16 bits ->  2**16 == 65536 distinct patterns.
# Signed ->  half negative, half non-negative: -2**15 .. 2**15 - 1
# Unsigned ->  all non-negative starting at 0: 0 .. 2**16 - 1
if SIGNED:
    VALUE_MIN, VALUE_MAX = -(2 ** 15), (2 ** 15) - 1 # -32768 .. 32767
else:
    VALUE_MIN, VALUE_MAX = 0, (2 ** 16) - 1 # 0 .. 65535


def make_random_array():
    """Build a sample array. Modify freely for your own test cases."""
    return [random.randint(VALUE_MIN, VALUE_MAX) for _ in range(ARRAY_LEN)]


def validate(values):
    """Data validation: refuse to send anything that breaks our contract."""
    if len(values) != ARRAY_LEN:
        raise ValueError(f"expected {ARRAY_LEN} integers, got {len(values)}")
    for i, v in enumerate(values):
        if not isinstance(v, int):
            raise ValueError(f"index {i}: {v!r} is not an integer")
        if not (VALUE_MIN <= v <= VALUE_MAX):
            raise ValueError(
                f"index {i}: {v} is outside the 16-bit range "
                f"{VALUE_MIN}..{VALUE_MAX}"
            )


def encode(values):
    """
    Turn the integer array into bytes.

    Wire format (every number is big-endian, a.k.a. 'network byte order',
    so sender and receiver agree on which byte comes first):
        HEADER
          [ count    : 2 bytes, unsigned ]  how many integers in total
          [ checksum : 2 bytes, unsigned ]  (sum of all values) mod 65536
        BODY  (one or more runs)
          [ value : 2 bytes ][ run length : 2 bytes, unsigned ]  x N

    Run-length encoding: rather than writing the value 7 fifty times, we
    write "value 7, length 50" once. A long sequence of the same integer
    therefore costs only 4 bytes no matter how long it is.
    """
    checksum = sum(values) & 0xFFFF     # Keep the low 16 bits as a fingerprint

    packet = bytearray()
    packet += len(values).to_bytes(2, "big", signed=False)   # Count
    packet += checksum.to_bytes(2, "big", signed=False)      # Checksum

    i = 0
    while i < len(values):
        v = values[i]
        run = 1
        # Grow the run while the next value is identical; cap at 65535,
        # The largest number a 2-byte unsigned length field can store.
        while i + run < len(values) and values[i + run] == v and run < 0xFFFF:
            run += 1
        packet += v.to_bytes(2, "big", signed=SIGNED)
        packet += run.to_bytes(2, "big", signed=False)
        i += run

    return bytes(packet)


def main():
    values = make_random_array()
    validate(values)                    # Stop now if the data is bad
    packet = encode(values)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Allow sending to a broadcast address. Harmless when TARGET_IP is a plain unicast/localhost address, required when it is x.x.x.255.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    sock.sendto(packet, (TARGET_IP, PORT))   # The single transmission
    sock.close()

    print(f"Sent {len(values)} integers as {len(packet)} bytes "
          f"to {TARGET_IP}:{PORT}")
    print("First 10 values:", values[:10])


if __name__ == "__main__":
    main()
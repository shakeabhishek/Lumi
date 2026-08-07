"""Probe for 3 APA102 LEDs on SPI0, as the ReSpeaker 2-Mics HAT v1 wires them.
Cycles red -> green -> blue -> off so a human can see whether anything lights."""
import time
import spidev

N = 3

def frame(rgb):
    # APA102: 4-byte start frame of zeros, then per-LED
    # [0xE0|brightness, B, G, R], then an end frame of 0xFF.
    out = [0x00] * 4
    for (r, g, b) in rgb:
        out += [0xE0 | 31, b, g, r]
    out += [0xFF] * 4
    return out

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 8000000
print("SPI0.0 opened at", spi.max_speed_hz, "Hz")

for name, colour in (("RED", (255,0,0)), ("GREEN", (0,255,0)), ("BLUE", (0,0,255))):
    print(f"  writing {name} to {N} LEDs — look at the HAT")
    spi.xfer2(frame([colour]*N))
    time.sleep(3.0)

print("  writing OFF")
spi.xfer2(frame([(0,0,0)]*N))
spi.close()
print("done — did any LED light up?")

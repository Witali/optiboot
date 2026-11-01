"""AVR instruction models for FlashRead256; not physical timing validation."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import build_mini
from test_expanded_ports import LegacyNew
from test_modern_audit import AVRModern
from test_legacy_uart import symaddr


class LegacyFlash(LegacyNew):
    def __init__(self, image, dev, cause=2):
        super().__init__(b'\xff' * max(0, 512-len(image)) + image, dev, cause)
        self.boot_start = dev['flash'] - len(image)
        self.flash = bytearray(b'\xff' * self.boot_start + image)
        self.pc = self.boot_start
        self.ucsrc, self.ubrrh = 0x86, 0


def make_cpu(chip, folder, cause=2, ready=True):
    dev = build_mini.DEVICES[chip]
    folder = Path(folder)
    image = (folder / (chip + '.bin')).read_bytes()
    obj = folder / (chip + '.o')
    cpu = (LegacyFlash(image, dev, cause) if dev['profile'] == 'legacy' else
           AVRModern(image, dev['flash'], dev['page'], dev['eeprom'], cause))
    cpu.rxwait_pc = cpu.boot_start + symaddr(obj, 'rx_wait')
    cpu.error_pc = cpu.boot_start + symaddr(obj, 'bad_packet')
    if ready:
        cpu.wait_ready()
    return cpu, image, dev


def address_packet(address):
    if address % 2:
        raise ValueError('Word-addressed Flash requires an even byte address')
    word = address // 2
    return bytes((0x55, word & 255, word >> 8, 0x20))


def write_packet(data, length=None, memory=0x46):
    length = len(data) if length is None else length
    return bytes((0x64, length >> 8, length & 255, memory)) + data + b' '


def read_packet(length, memory=0x46):
    return bytes((0x74, length >> 8, length & 255, memory, 0x20))

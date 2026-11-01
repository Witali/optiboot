"""Common device factories for software validation; no physical-chip claim."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import build_mini
from test_legacy_uart import symaddr
from test_expanded_ports import LegacyNew, Mega256New
from test_modern_audit import AVRModern
from test_128k import AVR128
from test_mega64_audit import AVR64
from test_tiny_virtual import TinyAVR
from test_soft_uart import SoftAVR
from test_r10_sigrow import SIGRDMixin


class StickyResetFlags:
    """MCUSR bits are write-zero-to-clear; writing one cannot create a flag."""
    def io_write(self, address, value):
        if address == self.reset_flags_address:
            self.io[address] = self.io.get(address, 0) & value & 255
            return
        return super().io_write(address, value)


class SoftByteUART:
    """Accelerate whole-memory protocol tests; waveform tests use real SoftAVR."""
    def step(self):
        if self.pc == self.byte_receive and self.rx:
            self.reg[16] = self.rx.popleft()
            self.pc = self.stack.pop()
            self.cycles += 1
            return
        if self.pc == self.byte_transmit:
            self.tx.append(self.reg[16])
            self.pc = self.stack.pop()
            self.cycles += 1
            return
        return super().step()


def create(chip, folder, cause=2, ready=True):
    folder = Path(folder)
    dev = build_mini.DEVICES[chip]
    image = (folder / (chip + '.bin')).read_bytes()
    obj = folder / (chip + '.o')
    profile = dev['profile']
    if profile == 'legacy':
        cpu = LegacyNew(image, dev, cause)
    elif profile == 'modern':
        cpu = AVRModern(image, dev['flash'], dev['page'], dev['eeprom'], cause)
    elif profile == 'modern128':
        cpu = AVR128(image, False, cause)
    elif profile == 'modern256':
        cpu = Mega256New(image, cause)
    elif profile == 'mega128':
        cpu = AVR128(image, True, cause)
    elif profile == 'mega64':
        cpu = AVR64(image, cause)
    elif profile.startswith('soft'):
        cpu = SoftAVR(image, dev, cause)
        cpu.__class__ = type('SoftProtocol', (SoftByteUART, type(cpu)), {})
        cpu.byte_receive = cpu.boot_start + symaddr(obj, 'rx_char')
        cpu.byte_transmit = cpu.boot_start + symaddr(obj, 'tx_char')
    elif profile in ('tiny841', 'tiny1634'):
        cpu = TinyAVR(image, dev, cause)
    else:
        raise ValueError('No instruction model for ' + profile)
    if dev['sigrow_lpm_supported_by_datasheet']:
        cpu.__class__ = type('SiliconSignature', (SIGRDMixin, type(cpu)), {})
        cpu.setup_signature(dev)
    cpu.__class__ = type('ResetFlags', (StickyResetFlags, type(cpu)), {})
    cpu.reset_flags_address = 0x55 if profile == 'tiny1634' else 0x54
    cpu.rxwait_pc = (cpu.byte_receive if profile.startswith('soft') else
                     cpu.boot_start + symaddr(obj, 'rx_wait'))
    cpu.error_pc = cpu.boot_start + symaddr(obj, 'error_loop')
    if ready:
        cpu.wait_ready()
    return cpu, image, dev

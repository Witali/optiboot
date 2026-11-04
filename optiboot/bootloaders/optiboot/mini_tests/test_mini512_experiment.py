"""Execute the opt-in 328PB Mini image; no physical timing is modeled.

Real AVRDUDE interoperability is exercised separately by verify_arduino.py
with --experimental-328pb-512 over its localhost-only instruction model.
"""
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import build_flashread
from flashread_models import address_packet, make_cpu, read_packet, write_packet
from test_legacy_uart import symaddr


class Mini512ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mini512-experiment-')
        cls.folder = Path(cls.temp.name) / 'atmega328pb'
        cls.info = build_flashread.one('atmega328pb', cls.folder,
                                       experimental_512=True)
        cls.folder8 = Path(cls.temp.name) / '8MHz' / 'atmega328pb'
        build_flashread.one('atmega328pb', cls.folder8, 8000000, 38400,
                            experimental_512=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cpu(self, cause=2, ready=True):
        cpu, image, dev = make_cpu('atmega328pb', self.folder, cause, ready)
        self.assertEqual((cpu.boot_start, len(image), dev['page']),
                         (0x7E00, 512, 128))
        return cpu

    @staticmethod
    def observe_spm(cpu):
        calls = []
        original = cpu.spm
        def observe():
            calls.append((cpu.io[cpu.spmcsr], cpu.z()))
            original()
        cpu.spm = observe
        return calls

    def reject(self, cpu, packet, *, no_spm=False):
        before = bytes(cpu.flash), bytes(cpu.eeprom)
        counts = cpu.erase_count, cpu.write_count
        calls = self.observe_spm(cpu)
        cpu.execute_until_error(packet, cpu.error_pc, limit=30000)
        self.assertEqual((bytes(cpu.flash), bytes(cpu.eeprom)), before)
        self.assertEqual((cpu.erase_count, cpu.write_count), counts)
        if no_spm:
            self.assertEqual(calls, [], 'Rejected request reached an SPM instruction')
        return calls

    def test_opt_in_is_separate_from_the_14_public_profiles(self):
        self.assertEqual(len(build_flashread.TARGETS), 14)
        self.assertNotIn('atmega328pb', build_flashread.TARGETS)
        self.assertNotIn('atmega328p', build_flashread.TARGETS)
        with self.assertRaises(ValueError):
            build_flashread.one('atmega328pb', self.folder / 'not-opted-in')
        with self.assertRaises(ValueError):
            build_flashread.one('atmega328p', self.folder / 'wrong-part',
                                experimental_512=True)

    def test_physical_layout_manifest_and_parameter_relocation(self):
        image = (self.folder / 'atmega328pb.bin').read_bytes()
        info = json.loads((self.folder / 'atmega328pb.json').read_text())
        self.assertEqual(info['edition'], 'mini-experimental-512')
        self.assertEqual((info['boot_bytes'], info['boot_start']), (512, '0x7E00'))
        self.assertEqual(info['bootsz1_0_bits'], '11')
        self.assertEqual(len(image), 512)
        self.assertEqual(image[-3:], bytes.fromhex('1e9516'))
        self.assertEqual(hashlib.sha256(image).hexdigest(), info['code_sha256'])
        self.assertTrue(info['requires_hardware_reset'])
        self.assertTrue(info['eeprom_busy_interlock'])
        self.assertTrue(info['flash_read'])
        self.assertTrue(info['flash_write'])
        self.assertFalse(info['eeprom_read'])
        self.assertFalse(info['eeprom_write'])
        parameter = symaddr(self.folder / 'atmega328pb.o', 'parameter_constant')
        self.assertLess(parameter, 256)
        self.assertEqual(image[parameter:parameter+2], bytes.fromhex('03fd'))
        self.assertEqual(image[info['code_bytes']:-3],
                         b'\xff' * (509-info['code_bytes']))

    def test_arduino_handshake_all_parameter_selectors_and_signature(self):
        cpu = self.cpu()
        for packet in (b'0 ', b'P ', b'B'+bytes(range(20))+b' ',
                       b'E'+bytes((0x20, 1, 2, 3, 4))+b' '):
            self.assertEqual(cpu.send(packet), b'\x14\x10')
        self.assertEqual(cpu.send(b'u '), bytes.fromhex('141e951610'))
        # Signature access leaves Z in 0x7Fxx. Parameters reside in 0x7Exx:
        # this catches a reused signature high byte after increasing Boot size.
        for selector in range(256):
            cpu.set_z(0x7FFF)
            self.assertEqual(cpu.send(bytes((0x41, selector, 0x20))),
                             b'\x14\x03\x10')

    def test_8mhz_image_parameter_signature_upper_page_and_boot_guard(self):
        cpu, image, _ = make_cpu('atmega328pb', self.folder8)
        self.assertEqual(cpu.send(b'u '), bytes.fromhex('141e951610'))
        for selector in range(256):
            self.assertEqual(cpu.send(bytes((0x41, selector, 0x20))),
                             b'\x14\x03\x10')
        data = bytes((i*43+9) & 255 for i in range(128))
        cpu.send(address_packet(0x7D80))
        self.assertEqual(cpu.send(write_packet(data)), b'\x14\x10')
        cpu.send(address_packet(0x7D80))
        self.assertEqual(cpu.send(read_packet(128)), b'\x14'+data+b'\x10')
        self.assertEqual(bytes(cpu.flash[0x7E00:]), image)
        cpu.send(address_packet(0x7E00))
        self.reject(cpu, write_packet(data), no_spm=True)

    def test_every_application_page_including_upper_16k_roundtrips(self):
        cpu = self.cpu()
        boot = bytes(cpu.flash[0x7E00:])
        eeprom = bytes(cpu.eeprom)
        for address in range(0, 0x7E00, 128):
            with self.subTest(page=f'{address:04X}'):
                data = bytes((address//128*29+i*73+11) & 255 for i in range(128))
                self.assertEqual(cpu.send(address_packet(address)), b'\x14\x10')
                self.assertEqual(cpu.send(write_packet(data)), b'\x14\x10')
                self.assertEqual(bytes(cpu.flash[address:address+128]), data)
                self.assertEqual(cpu.send(address_packet(address)), b'\x14\x10')
                self.assertEqual(cpu.send(read_packet(128)), b'\x14'+data+b'\x10')
        self.assertEqual((cpu.erase_count, cpu.write_count), (252, 252))
        self.assertEqual(bytes(cpu.flash[0x7E00:]), boot)
        self.assertEqual(bytes(cpu.eeprom), eeprom)

    def test_all_supported_read_lengths_at_first_and_last_application_pages(self):
        cpu = self.cpu()
        for address in (0, 0x7D80):
            data = bytes((address//128+i*17) & 255 for i in range(128))
            cpu.flash[address:address+128] = data
            for length in range(1, 129):
                with self.subTest(address=address, length=length):
                    cpu.send(address_packet(address))
                    self.assertEqual(cpu.send(read_packet(length)),
                                     b'\x14'+data[:length]+b'\x10')

    def test_every_boot_page_rejects_reads_and_writes_before_any_spm(self):
        for address in range(0x7E00, 0x8000, 128):
            for packet in (read_packet(1), read_packet(128),
                           write_packet(b'\xa5'*128)):
                with self.subTest(address=f'{address:04X}', opcode=packet[0]):
                    cpu = self.cpu()
                    self.assertEqual(cpu.send(address_packet(address)), b'\x14\x10')
                    self.reject(cpu, packet, no_spm=True)

    def test_invalid_lengths_and_memory_types_never_reach_spm(self):
        packets = [read_packet(n) for n in (0, 129, 255, 256, 384)]
        packets += [write_packet(bytes(n), n)
                    for n in (0, 1, 2, 126, 127, 129, 130, 255, 256, 384)]
        packets += [packet for memory in (0x45, 0x58, 0)
                    for packet in (read_packet(1, memory),
                                   write_packet(bytes(128), memory=memory))]
        for packet in packets:
            with self.subTest(packet=packet[:4].hex()):
                cpu = self.cpu()
                cpu.send(address_packet(0x7D80))
                self.reject(cpu, packet, no_spm=True)

    def test_alignment_physical_end_and_overflow_are_rejected(self):
        for address in (2, 126, 0x4002, 0x7D82, 0x8000, 0xFF80):
            for packet in (read_packet(1), write_packet(bytes(128))):
                with self.subTest(address=address, opcode=packet[0]):
                    cpu = self.cpu()
                    cpu.send(address_packet(address))
                    self.reject(cpu, packet, no_spm=True)
        for packet in (b'U\x00\x80 ', b'U\xff\xff '):
            self.reject(self.cpu(), packet, no_spm=True)

    def test_invalid_eop_does_not_erase_or_write_the_page(self):
        cpu = self.cpu()
        cpu.flash[0x7D80:0x7E00] = b'\xa5'*128
        cpu.send(address_packet(0x7D80))
        calls = self.reject(cpu, write_packet(bytes(128))[:-1]+b'!')
        # The Mini contract buffers payload before EOP; only commit is gated.
        self.assertEqual([command for command, _ in calls], [1]*64)
        for packet in (b'0!', b'U\x00\x00!', read_packet(1)[:-1]+b'!'):
            self.reject(self.cpu(), packet, no_spm=True)

    def test_incomplete_payload_and_missing_eop_cannot_commit(self):
        for count in (0, 1, 63, 127, 128):
            with self.subTest(payload_bytes=count):
                cpu = self.cpu()
                cpu.send(address_packet(0x7D80))
                before = bytes(cpu.flash), bytes(cpu.eeprom)
                output = len(cpu.tx)
                cpu.rx.extend(write_packet(bytes(128))[:4+count])
                for _ in range(5000):
                    cpu.step()
                self.assertEqual((bytes(cpu.flash), bytes(cpu.eeprom)), before)
                self.assertEqual((cpu.erase_count, cpu.write_count), (0, 0))
                self.assertEqual(len(cpu.tx), output)
                # The model has no asynchronous watchdog: it proves waiting
                # without commit, not the time taken for physical recovery.

    def test_eeprom_busy_interlocks_even_the_first_buffer_fill(self):
        cpu = self.cpu()
        cpu.send(address_packet(0x7D80))
        calls = self.observe_spm(cpu)
        cpu.io[0x3F] = 2
        data = bytes((i*13+7) & 255 for i in range(128))
        cpu.rx.extend(write_packet(data))
        for _ in range(2000):
            cpu.step()
        self.assertEqual(calls, [])
        self.assertEqual(cpu.page_buf, {})
        self.assertEqual((cpu.erase_count, cpu.write_count), (0, 0))
        cpu.io[0x3F] = 0
        for _ in range(30000):
            if not cpu.rx and cpu.pc == cpu.rxwait_pc:
                break
            cpu.step()
        else:
            self.fail('Firmware did not resume after EEPROM busy cleared')
        self.assertEqual(bytes(cpu.flash[0x7D80:0x7E00]), data)
        self.assertEqual([command for command, _ in calls], [1]*64+[3, 5, 0x11])

    def test_randomized_reset_entry_mcusr_watchdog_and_pc_wrap(self):
        for cause in range(16):
            with self.subTest(cause=cause):
                cpu = self.cpu(cause, ready=False)
                rng = random.Random(328512+cause)
                cpu.reg[:] = [rng.randrange(256) for _ in cpu.reg]
                for _ in range(300):
                    if cpu.pc in (0, cpu.rxwait_pc):
                        break
                    cpu.step()
                self.assertEqual(cpu.io[0x54], 0)
                self.assertEqual(cpu.wdt_writes, [0x18, 0 if cause & 8 else 0x0E])
                if cause & 8:
                    self.assertEqual(cpu.pc, 0, 'FLASHEND+1 exit failed to wrap to reset')
                    self.assertEqual(cpu.reg[1], 0)
                else:
                    self.assertEqual(cpu.pc, cpu.rxwait_pc)
                    self.assertEqual(cpu.io[0xC1], 0x18)
                    self.assertEqual(cpu.io[0xC4], 16)
                    self.assertEqual(cpu.io_read(0xC5), 0)

    def test_leave_requests_short_watchdog_without_memory_operations(self):
        cpu = self.cpu()
        calls = self.observe_spm(cpu)
        self.assertEqual(cpu.send(b'Q '), b'\x14\x10')
        self.assertEqual(cpu.wdt_writes[-2:], [0x18, 0x08])
        self.assertEqual(calls, [])
        # WDT elapsed time/reset is deliberately outside this instruction model.

    def test_universal_is_not_an_isp_or_signature_read_interface(self):
        for command in (bytes.fromhex('563000000020'),
                        bytes.fromhex('565800000020'),
                        bytes.fromhex('56aca0000020')):
            self.reject(self.cpu(), command, no_spm=True)


if __name__ == '__main__':
    unittest.main()

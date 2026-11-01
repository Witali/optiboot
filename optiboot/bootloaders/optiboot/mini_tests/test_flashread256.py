"""Build and execute every FlashRead256 device at both reference clocks."""
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
from flashread_models import make_cpu, address_packet, read_packet, write_packet


class FlashRead256Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='flashread256-')
        cls.outputs = {}
        for chip in build_flashread.TARGETS:
            for hz, baud in ((8000000, 38400), (16000000, 115200)):
                folder = Path(cls.temp.name) / chip / str(hz)
                cls.outputs[chip, hz] = folder
                build_flashread.one(chip, folder, hz, baud)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def reject(self, cpu, packet):
        before = bytes(cpu.flash), bytes(cpu.eeprom)
        erase, write = cpu.erase_count, cpu.write_count
        cpu.rx.extend(packet)
        for _ in range(20000):
            if cpu.pc == cpu.error_pc:
                break
            cpu.step()
        else:
            self.fail('Invalid request did not enter watchdog recovery')
        self.assertEqual((bytes(cpu.flash), bytes(cpu.eeprom)), before)
        self.assertEqual((cpu.erase_count, cpu.write_count), (erase, write))

    def test_real_256_byte_layout_and_hashes(self):
        self.assertEqual(len(build_flashread.TARGETS), 14)
        for (chip, hz), folder in self.outputs.items():
            with self.subTest(chip=chip, hz=hz):
                blob = (folder / (chip + '.bin')).read_bytes()
                meta = json.loads((folder / (chip + '.json')).read_text())
                self.assertEqual(len(blob), 256)
                self.assertLessEqual(meta['code_bytes'] + 3, 256)
                self.assertEqual(blob[-3:], bytes(build_flashread.build_mini.DEVICES[chip]['sig']))
                self.assertEqual(hashlib.sha256(blob).hexdigest(), meta['code_sha256'])
                self.assertEqual(meta['bootsz1_0_bits'], '11')
                self.assertTrue(meta['eeprom_busy_interlock'])

    def test_host_handshake_and_all_parameter_ids(self):
        for (chip, hz), folder in self.outputs.items():
            with self.subTest(chip=chip, hz=hz):
                cpu, _, dev = make_cpu(chip, folder)
                for packet in (b'0 ', b'P ', b'B' + bytes(range(20)) + b' ',
                               b'E' + bytes((0x20, 1, 2, 3, 4)) + b' '):
                    self.assertEqual(cpu.send(packet), b'\x14\x10')
                for parameter in range(256):
                    self.assertEqual(cpu.send(bytes((0x41, parameter, 0x20))), b'\x14\x03\x10')
                self.assertEqual(cpu.send(b'u '), b'\x14' + bytes(dev['sig']) + b'\x10')
                self.assertEqual(cpu.send(b'Q '), b'\x14\x10')

    def test_first_last_pages_and_every_read_length(self):
        for (chip, hz), folder in self.outputs.items():
            with self.subTest(chip=chip, hz=hz):
                cpu, image, dev = make_cpu(chip, folder)
                page = dev['page']
                for address in (0, page, cpu.boot_start-page):
                    data = bytes((i*73 + address//page) & 255 for i in range(page))
                    self.assertEqual(cpu.send(address_packet(address)), b'\x14\x10')
                    self.assertEqual(cpu.send(write_packet(data)), b'\x14\x10')
                    self.assertEqual(cpu.flash[address:address+page], data)
                    for length in range(1, page+1):
                        cpu.send(address_packet(address))
                        self.assertEqual(cpu.send(read_packet(length)), b'\x14'+data[:length]+b'\x10')
                self.assertEqual(cpu.flash[cpu.boot_start:], image)

    def test_invalid_lengths_memory_alignment_and_boot(self):
        for (chip, hz), folder in self.outputs.items():
            dev = build_flashread.build_mini.DEVICES[chip]
            page = dev['page']
            for packet in (read_packet(0), read_packet(page+1), read_packet(256),
                           read_packet(1, 0x45), write_packet(bytes(page), page-1),
                           write_packet(bytes(page), page+1), write_packet(bytes(page), 0x100+page),
                           write_packet(bytes(page), memory=0x45)):
                with self.subTest(chip=chip, hz=hz, packet=packet[:4].hex()):
                    cpu, _, _ = make_cpu(chip, folder)
                    cpu.send(address_packet(0))
                    self.reject(cpu, packet)
            for address in (2, dev['flash']-256, dev['flash'], dev['flash']+page):
                for packet in (read_packet(page), write_packet(bytes(page))):
                    with self.subTest(chip=chip, hz=hz, address=address):
                        cpu, _, _ = make_cpu(chip, folder)
                        cpu.send(address_packet(address))
                        self.reject(cpu, packet)
            with self.subTest(chip=chip, hz=hz, overflow=True):
                cpu, _, _ = make_cpu(chip, folder)
                self.reject(cpu, b'U\x00\x80 ')

    def test_bad_and_incomplete_packets_preserve_flash(self):
        for (chip, hz), folder in self.outputs.items():
            with self.subTest(chip=chip, hz=hz):
                cpu, _, dev = make_cpu(chip, folder)
                address = cpu.boot_start-dev['page']
                cpu.flash[address:cpu.boot_start] = b'\xa5' * dev['page']
                cpu.send(address_packet(address))
                self.reject(cpu, write_packet(bytes(dev['page']))[:-1] + b'!')
                for count in (0, 1, dev['page']//2, dev['page']-1):
                    cpu, _, _ = make_cpu(chip, folder)
                    cpu.send(address_packet(address))
                    before = bytes(cpu.flash)
                    cpu.rx.extend(write_packet(bytes(dev['page']))[:4+count])
                    for _ in range(3000):
                        cpu.step()
                    self.assertEqual(bytes(cpu.flash), before)
                    self.assertEqual((cpu.erase_count, cpu.write_count), (0, 0))

    def test_every_boot_page_is_rejected_before_any_spm_instruction(self):
        for (chip, hz), folder in self.outputs.items():
            dev = build_flashread.build_mini.DEVICES[chip]
            for address in range(dev['flash']-256, dev['flash'], dev['page']):
                with self.subTest(chip=chip, hz=hz, boot_page=address):
                    cpu, _, _ = make_cpu(chip, folder)
                    calls = []
                    original = cpu.spm
                    def observe():
                        calls.append(cpu.z())
                        original()
                    cpu.spm = observe
                    self.assertEqual(cpu.send(address_packet(address)), b'\x14\x10')
                    self.reject(cpu, write_packet(bytes([0xa5]*dev['page'])))
                    self.assertEqual(calls, [], 'Boot request reached SPM, including buffer fill')

    def test_eeprom_busy_blocks_spm_until_completion(self):
        for (chip, hz), folder in self.outputs.items():
            with self.subTest(chip=chip, hz=hz):
                cpu, _, dev = make_cpu(chip, folder)
                cpu.send(address_packet(0))
                eecr = 0x3f if dev['profile'] == 'modern' else 0x3c
                cpu.io[eecr] = 2
                cpu.rx.extend(write_packet(bytes([0x69]*dev['page'])))
                for _ in range(1500):
                    cpu.step()
                self.assertEqual((cpu.erase_count, cpu.write_count), (0, 0))
                self.assertFalse(cpu.page_buf)
                cpu.io[eecr] = 0
                for _ in range(20000):
                    if not cpu.rx and cpu.pc == cpu.rxwait_pc:
                        break
                    cpu.step()
                self.assertEqual(cpu.flash[:dev['page']], bytes([0x69]*dev['page']))

    def test_reset_entry_with_unknown_register_contents(self):
        for (chip, hz), folder in self.outputs.items():
            for cause in (0, 1, 2, 4, 8, 10, 15):
                with self.subTest(chip=chip, hz=hz, cause=cause):
                    cpu, _, _ = make_cpu(chip, folder, cause, ready=False)
                    rng = random.Random(cause + hz)
                    cpu.reg[:] = [rng.randrange(256) for _ in cpu.reg]
                    for steps in range(200):
                        if cpu.pc == cpu.rxwait_pc or cpu.pc == 0:
                            break
                        cpu.step()
                    self.assertEqual(cpu.io.get(0x54), 0)
                    if cause & 8:
                        self.assertEqual(cpu.pc, 0)
                        self.assertEqual(cpu.reg[1], 0)
                    else:
                        self.assertEqual(cpu.pc, cpu.rxwait_pc)

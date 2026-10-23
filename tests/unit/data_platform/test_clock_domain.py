"""Presentation changes are not boot changes; legacy records stay immutable."""
import hashlib
import time
import unittest
from unittest.mock import patch

from uteki.data_platform.application.execution_clock import clock_domain, start_clock
from uteki.data_platform.contracts.common import CatalogError

MODULE='uteki.data_platform.application.execution_clock'


class ClockDomainTests(unittest.TestCase):
    def domain(self,raw,*,version=2):
        with patch(MODULE+'.sys.platform','darwin'),patch(MODULE+'.subprocess.check_output',return_value=raw):
            return clock_domain(version=version)

    def test_presentation_changes_preserve_boot_but_numeric_changes_do_not(self):
        utc=b'{ sec = 100, usec = 123 } Thu Jan 1 00:01:40 1970\n'
        local=b'{ sec = 100, usec = 123 } Thu Jan 1 08:01:40 1970\n'
        self.assertEqual(self.domain(utc),self.domain(local))
        self.assertNotEqual(self.domain(utc),self.domain(local.replace(b'123',b'124')))
        self.assertNotEqual(self.domain(utc),self.domain(local.replace(b'100',b'101')))
        self.assertNotEqual(self.domain(utc,version=1),self.domain(local,version=1))
        expected=hashlib.sha256(b'darwin'+utc+time.get_clock_info('monotonic').implementation.encode()).hexdigest()
        self.assertEqual(self.domain(utc,version=1),expected)

    def test_invalid_numeric_metadata_or_version_never_gets_a_comparable_domain(self):
        for raw in (b'',b'{ sec = -1, usec = 0 }',b'{ sec = 1, usec = 1000000 }',b'formatted date only'):
            with self.subTest(raw=raw),self.assertRaises(CatalogError):self.domain(raw)
        for version in (0,4,'2',True,None):
            with self.subTest(version=version),self.assertRaises(CatalogError):
                self.domain(b'{ sec = 1, usec = 0 }',version=version)

    def test_boot_metadata_unavailable_keeps_in_process_clock_without_recovery_claim(self):
        with patch(MODULE+'._boot_metadata',side_effect=CatalogError('RECOVERY_REQUIRED','not available')):
            value=start_clock(2.0,1.0)
        self.assertIsNone(value['domain'])
        self.assertEqual(value['domain_version'],3)
        self.assertEqual(value['started_monotonic'],2.0)
        self.assertIn('not available',value['domain_unavailable'])

    def test_boot_session_identity_survives_calendar_adjustment_but_not_reboot(self):
        boot=b'12345678-1234-4234-8234-123456789ABC\n'
        def read(command,**kwargs):
            self.assertEqual(command[-1],'kern.bootsessionuuid')
            return boot
        with patch(MODULE+'.sys.platform','darwin'),patch(MODULE+'.subprocess.check_output',side_effect=read):
            first=clock_domain()
            self.assertEqual(first,start_clock(2.0,0)['domain'])
        self.assertEqual(first,self.domain(boot.lower(),version=3))
        self.assertNotEqual(first,self.domain(boot.replace(b'12345678-',b'22345678-'),version=3))
        for invalid in (b'',b'{ sec = 100, usec = 123 }',b'not-a-boot-uuid'):
            with self.subTest(invalid=invalid),self.assertRaises(CatalogError):self.domain(invalid,version=3)


if __name__=='__main__':unittest.main()

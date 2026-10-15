"""Behavioral acceptance of the frozen content contract; synthetic bytes only."""
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from uteki.data_platform.contracts import InputManifest, MissingResource, ObjectRef, PresentResource
from uteki.data_platform.content import ContentStore, ContentStoreError

VERSION = 'uteki-input-manifest-v1'
EMPTY_SHA = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


class ContractTests(unittest.TestCase):
    def manifest(self, **changes):
        fields = dict(schema_version=VERSION, main=ObjectRef(sha256=EMPTY_SHA, byte_length=0),
                      main_source_url=None, resources=())
        return InputManifest(**(fields | changes))

    def test_reference_strict_fields_and_no_business_identity(self):
        for changes in ({'sha256':'../escape'}, {'sha256':'A'*64}, {'sha256':EMPTY_SHA+'\n'},
                        {'byte_length':True}, {'byte_length':-1}, {'byte_length':'0'},
                        {'asset_id':'invented'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ObjectRef(**(dict(sha256=EMPTY_SHA,byte_length=0) | changes))

    def test_exact_canonical_wire_bytes(self):
        expected = ('{"main":{"byte_length":0,"sha256":"' + EMPTY_SHA +
                    '"},"main_source_url":null,"resources":[],"schema_version":"' + VERSION + '"}').encode()
        item=self.manifest()
        self.assertEqual(item.canonical_bytes(), expected)
        self.assertEqual(item.content_sha256(), hashlib.sha256(expected).hexdigest())
        self.assertEqual(InputManifest.model_validate_json(expected), item)

    def test_resource_order_does_not_change_hash(self):
        a=MissingResource(status='missing', resource_key='图 a', source_url=None, reason='not fetched')
        b=PresentResource(status='present', resource_key='../opaque-key', source_url='https://example.invalid/a',
                          object_ref=ObjectRef(sha256=EMPTY_SHA, byte_length=0))
        self.assertEqual(self.manifest(resources=(a,b)).canonical_bytes(), self.manifest(resources=(b,a)).canonical_bytes())
        self.assertIn('图 a'.encode(), self.manifest(resources=(a,b)).canonical_bytes())

    def test_explicit_fields_discriminators_and_unique_resource_keys(self):
        valid=self.manifest().model_dump()
        invalid=[{k:v for k,v in valid.items() if k!=field} for field in valid]
        invalid += [valid | {'schema_version':'v2'}, valid | {'unknown':1}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                InputManifest.model_validate(value)
        resource=MissingResource(status='missing',resource_key='x',source_url=None,reason='404')
        with self.assertRaises(ValidationError): self.manifest(resources=(resource,resource))
        for value in (
            dict(status='missing',resource_key='x',source_url=None,reason='404',object_ref=valid['main']),
            dict(status='present',resource_key='x',source_url=None),
            dict(status='unknown',resource_key='x',source_url=None,reason='404'),
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.manifest(resources=(value,))

    def test_invalid_text_rejected_before_hashing(self):
        for bad in (' ', '\t', 'bad\x00text', 'bad\x7ftext', '\ud800'):
            for field in ('resource_key','source_url','reason'):
                with self.subTest(field=field,bad=repr(bad)), self.assertRaises(ValidationError):
                    MissingResource(**(dict(status='missing', resource_key='key', source_url=None,reason='absent') | {field:bad}))
            with self.subTest(main_source_url=repr(bad)), self.assertRaises(ValidationError):
                self.manifest(main_source_url=bad)

    def test_canonical_methods_revalidate_copied_and_constructed_instances(self):
        invalid=[self.manifest().model_copy(update={'schema_version':'wrong'}),
                 self.manifest(main=self.manifest().main).model_copy(update={'main': ObjectRef.model_construct(sha256=EMPTY_SHA,byte_length=-1)})]
        for item in invalid:
            for method in (item.canonical_bytes,item.content_sha256):
                with self.subTest(method=method.__name__), self.assertRaises(ValidationError): method()
        with self.assertRaises(ValidationError): self.manifest().main.byte_length=2


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='uteki-content-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.store=ContentStore(self.root)

    def path(self, ref):
        return self.root/'objects'/'sha256'/ref.sha256[:2]/ref.sha256

    def assert_code(self, code, function, *args):
        with self.assertRaises(ContentStoreError) as raised: function(*args)
        self.assertEqual(raised.exception.code,code)
        return raised.exception

    def manifest(self, main, resources=()):
        return InputManifest(schema_version=VERSION,main=main,main_source_url=None,resources=resources)

    def test_root_must_be_explicit_existing_absolute_directory(self):
        with self.assertRaises(TypeError): ContentStore()
        file=self.root/'file'; file.write_bytes(b'file')
        for root in (None,0,b'/', '', ' ', '.', Path('.'), 'relative', self.root/'absent',file):
            with self.subTest(root=root): self.assert_code('INVALID_DATA_ROOT',ContentStore,root)
        self.assertFalse((self.root/'absent').exists())
        alias=self.root/'root-alias'; alias.symlink_to(self.root,target_is_directory=True)
        self.assertEqual(ContentStore(alias).data_root,self.root)

    def test_root_io_error_is_normalized(self):
        failure=PermissionError(errno.EACCES,'synthetic root access denied')
        with patch.object(Path,'stat',side_effect=failure):
            error=self.assert_code('INVALID_DATA_ROOT',ContentStore,self.root)
        self.assertIs(error.__cause__,failure)

    def test_empty_and_binary_round_trip_and_deduplication(self):
        for raw in (b'',b'\x00\xff\n\x80',bytes(range(256))*257):
            with self.subTest(size=len(raw)):
                ref=self.store.put_object(raw)
                self.assertEqual(ref.sha256,hashlib.sha256(raw).hexdigest())
                self.assertEqual(ref.byte_length,len(raw))
                old_stat=self.path(ref).stat()
                self.assertEqual(self.store.put_object(raw),ref)
                self.assertEqual(self.path(ref).stat().st_ino,old_stat.st_ino)
                self.assertEqual(self.path(ref).stat().st_mtime_ns,old_stat.st_mtime_ns)
                self.assertEqual(ContentStore(self.root).read_object(ref),raw)
        self.assertFalse(list(self.root.rglob('.pending-*')))

    def test_new_object_does_not_overwrite_old_reference(self):
        old=self.store.put_object(b'old original')
        new=self.store.put_object(b'new original')
        self.assertNotEqual(old,new)
        self.assertEqual(ContentStore(self.root).read_object(old),b'old original')
        self.assertEqual(ContentStore(self.root).read_object(new),b'new original')

    def test_object_and_reference_input_errors(self):
        for raw in ('bytes',None,bytearray(b'bytes')):
            with self.subTest(raw=raw): self.assert_code('INVALID_OBJECT',self.store.put_object,raw)
        for ref in (None,{'sha256':'bad','byte_length':1},ObjectRef.model_construct(sha256='../../x',byte_length=1)):
            with self.subTest(ref=ref): self.assert_code('INVALID_REFERENCE',self.store.read_object,ref)

    def test_missing_object_and_wrong_length_are_distinct(self):
        missing=ObjectRef(sha256=EMPTY_SHA,byte_length=0)
        self.assert_code('OBJECT_MISSING',self.store.read_object,missing)
        ref=self.store.put_object(b'text')
        self.assert_code('OBJECT_CORRUPT',self.store.read_object,ref.model_copy(update={'byte_length':3}))
        self.path(ref).unlink()
        self.assert_code('OBJECT_MISSING',self.store.read_object,ref)

    def test_same_length_corruption_is_not_repaired_by_read_or_put(self):
        ref=self.store.put_object(b'good')
        path=self.path(ref); path.chmod(0o600); path.write_bytes(b'evil')
        self.assert_code('OBJECT_CORRUPT',self.store.read_object,ref)
        self.assert_code('OBJECT_CORRUPT',self.store.put_object,b'good')
        self.assertEqual(path.read_bytes(),b'evil')

    def test_internal_symlinks_and_special_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root/'objects').symlink_to(outside,target_is_directory=True)
            self.assert_code('UNSAFE_OBJECT_PATH',self.store.put_object,b'one')
            self.assertEqual(list(Path(outside).iterdir()),[])
            (self.root/'objects').unlink()
            ref=self.store.put_object(b'one'); path=self.path(ref); path.unlink()
            target=Path(outside)/'external'; target.write_bytes(b'one'); path.symlink_to(target)
            self.assert_code('UNSAFE_OBJECT_PATH',self.store.read_object,ref)
            self.assert_code('UNSAFE_OBJECT_PATH',self.store.put_object,b'one')
            path.unlink(); os.mkfifo(path)
            self.assert_code('UNSAFE_OBJECT_PATH',self.store.read_object,ref)

    def test_manifest_round_trip_tracks_resources_gaps_and_changes(self):
        main=self.store.put_object(b'<html>synthetic</html>')
        first=self.store.put_object(b'figure-v1'); second=self.store.put_object(b'figure-v2')
        present=lambda ref: PresentResource(status='present',resource_key='figure',source_url=None,object_ref=ref)
        gap=MissingResource(status='missing',resource_key='appendix',source_url=None,reason='not fetched')
        old=self.manifest(main,(present(first),gap))
        old_ref=self.store.put_manifest(old)
        new_ref=self.store.put_manifest(self.manifest(main,(present(second),gap)))
        resolved_ref=self.store.put_manifest(self.manifest(main,(present(second),)))
        self.assertEqual(len({old_ref.sha256,new_ref.sha256,resolved_ref.sha256}),3)
        self.assertEqual(ContentStore(self.root).read_manifest(old_ref).canonical_bytes(),old.canonical_bytes())
        self.assertEqual(self.store.read_object(old_ref),old.canonical_bytes())
        self.assertEqual(old_ref.sha256,old.content_sha256())
        self.assertIsNone(self.store.verify_manifest(old))
        changed_reason=self.manifest(main,(present(first),gap.model_copy(update={'reason':'404'})))
        self.assertNotEqual(self.store.put_manifest(changed_reason),old_ref)
        self.assertNotEqual(self.store.put_manifest(old.model_copy(update={'main_source_url':'https://example.invalid/a'})),old_ref)
        new_main=self.store.put_object(b'<html>synthetic revision</html>')
        changed=[old.model_copy(update={'main':new_main}),
                 self.manifest(main,(present(first).model_copy(update={'resource_key':'renamed-figure'}),gap)),
                 self.manifest(main,(present(first).model_copy(update={'source_url':'https://example.invalid/figure'}),gap))]
        refs=[self.store.put_manifest(item) for item in changed]
        self.assertEqual(len({old_ref.sha256,*(ref.sha256 for ref in refs)}),4)
        self.assertEqual(ContentStore(self.root).read_object(ContentStore(self.root).read_manifest(old_ref).main),
                         b'<html>synthetic</html>')

    def test_present_missing_and_corrupt_never_become_declared_gaps(self):
        main=self.store.put_object(b'main'); extra=self.store.put_object(b'extra')
        item=self.manifest(main,(PresentResource(status='present',resource_key='extra',source_url=None,object_ref=extra),))
        ref=self.store.put_manifest(item)
        self.path(extra).unlink()
        self.assert_code('OBJECT_MISSING',self.store.put_manifest,item)
        self.assert_code('OBJECT_MISSING',self.store.read_manifest,ref)
        self.store.put_object(b'extra'); self.path(extra).chmod(0o600); self.path(extra).write_bytes(b'wrong')
        self.assert_code('OBJECT_CORRUPT',self.store.read_manifest,ref)
        self.assert_code('OBJECT_CORRUPT',self.store.verify_manifest,item)

    def test_invalid_manifest_structure_and_canonical_bytes_are_rejected(self):
        main=self.store.put_object(b'main'); valid=self.manifest(main)
        for item in (None,valid.model_copy(update={'schema_version':'v2'})):
            self.assert_code('INVALID_MANIFEST',self.store.put_manifest,item)
        encoded=valid.canonical_bytes()
        for raw in (b'not json',b'\xff',b'{}',encoded+b'\n',encoded.replace(b'"resources":[]',b'"resources":[],"resources":[]')):
            with self.subTest(raw=raw):
                ref=self.store.put_object(raw)
                self.assert_code('INVALID_MANIFEST',self.store.read_manifest,ref)

    def test_disk_error_preserves_cause_and_does_not_return_success(self):
        failure=OSError(errno.ENOSPC,'synthetic full disk')
        with patch('uteki.data_platform.content.store.tempfile.mkstemp',side_effect=failure):
            error=self.assert_code('STORAGE_IO_ERROR',self.store.put_object,b'new')
        self.assertIs(error.__cause__,failure)
        self.assertFalse(any(p.is_file() for p in self.root.rglob('*')))

    def test_file_fsync_link_and_directory_fsync_failure_are_retryable(self):
        old=self.store.put_object(b'old')
        real_fsync=os.fsync
        for stage in ('file_fsync','link','directory_after_link'):
            raw=('payload-'+stage).encode(); ref=ObjectRef(sha256=hashlib.sha256(raw).hexdigest(),byte_length=len(raw))
            def fsync(fd):
                is_file=stat.S_ISREG(os.fstat(fd).st_mode)
                if (stage=='file_fsync' and is_file) or (stage=='directory_after_link' and not is_file and self.path(ref).exists()):
                    raise OSError(errno.EIO,'synthetic fsync failure')
                return real_fsync(fd)
            with self.subTest(stage=stage):
                if stage=='link':
                    with patch('uteki.data_platform.content.store.os.link',side_effect=OSError(errno.EIO,'synthetic link failure')):
                        self.assert_code('STORAGE_IO_ERROR',self.store.put_object,raw)
                else:
                    with patch('uteki.data_platform.content.store.os.fsync',side_effect=fsync):
                        self.assert_code('STORAGE_IO_ERROR',self.store.put_object,raw)
                self.assertEqual(ContentStore(self.root).read_object(old),b'old')
                if stage!='directory_after_link': self.assertFalse(self.path(ref).exists())
                else: self.assertEqual(self.store.read_object(ref),raw)
                self.assertEqual(self.store.put_object(raw),ref)
                self.assertEqual(ContentStore(self.root).read_object(ref),raw)

    def test_failed_directory_creation_sync_is_retried(self):
        real_fsync=os.fsync; seen=[]
        def fail_root(fd):
            if os.fstat(fd).st_ino == self.root.stat().st_ino:
                raise OSError(errno.EIO,'synthetic root-directory fsync failure')
            return real_fsync(fd)
        with patch('uteki.data_platform.content.store.os.fsync',side_effect=fail_root):
            self.assert_code('STORAGE_IO_ERROR',self.store.put_object,b'after interrupted directory creation')
        def record(fd):
            seen.append(os.fstat(fd).st_ino); return real_fsync(fd)
        with patch('uteki.data_platform.content.store.os.fsync',side_effect=record):
            ref=self.store.put_object(b'after interrupted directory creation')
        self.assertIn(self.root.stat().st_ino,seen)
        self.assertEqual(self.store.read_object(ref),b'after interrupted directory creation')

    def test_partial_temporary_write_cannot_become_final_object(self):
        raw=b'full payload'; real_fdopen=os.fdopen
        class PartialWriter:
            def __init__(self,fd,mode): self.stream=real_fdopen(fd,mode)
            def __enter__(self): self.stream.__enter__(); return self
            def __exit__(self,*args): return self.stream.__exit__(*args)
            def write(self,data): self.stream.write(data[:2]); raise OSError(errno.ENOSPC,'synthetic partial write')
        with patch('uteki.data_platform.content.store.os.fdopen',side_effect=PartialWriter):
            self.assert_code('STORAGE_IO_ERROR',self.store.put_object,raw)
        ref=ObjectRef(sha256=hashlib.sha256(raw).hexdigest(),byte_length=len(raw))
        self.assert_code('OBJECT_MISSING',self.store.read_object,ref)
        self.assertEqual(self.store.read_object(self.store.put_object(raw)),raw)


if __name__ == '__main__':
    unittest.main()

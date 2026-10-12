"""Private transfer integrity and destination boundaries, entirely synthetic/offline."""
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import transfer_local_state as transfer


class TransferLocalStateTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve();self.root=self.base/'repo';self.root.mkdir()
        self.dialogue=self.base/'dialogue';self.dialogue.mkdir()
        self.archive=self.base/'private.tar.gz'

    def archive_of(self,files,*,wrong_hash=False,symlink=False,directories=None,
                   schema='uteki-private-transfer-v1',output_selections=None):
        manifest=dict(schema='uteki-private-transfer-v1',repository_root='/old/repo',dialogue_root='/old/dialogue',
            credentials_included=False,files={name:dict(sha256='0'*64 if wrong_hash else transfer.digest(raw),bytes=len(raw)) for name,raw in files.items()})
        manifest['schema']=schema
        if output_selections is not None:manifest['output_selections']=output_selections
        if directories is not None:manifest['directories']=directories
        with tarfile.open(self.archive,'w:gz') as archive:
            for name,raw in files.items():
                item=tarfile.TarInfo(name);item.size=len(raw)
                if symlink:item.type=tarfile.SYMTYPE;item.linkname='/outside'
                archive.addfile(item,io.BytesIO(raw))
            raw=json.dumps(manifest).encode();item=tarfile.TarInfo('transfer-manifest.json');item.size=len(raw)
            archive.addfile(item,io.BytesIO(raw))

    def test_create_excludes_env_and_cache_and_roundtrips_private_bytes(self):
        files={'data/source.bin':b'\x00original','data/.env':b'API_KEY=do-not-copy',
            'experiments/case/result.json':b'{"candidate":true}',
            'experiments/case/__pycache__/code.pyc':b'cache'}
        for name,raw in files.items():
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        (self.dialogue/'history.json').write_bytes(b'{"private":"context"}')
        (self.dialogue/'.env.production').write_bytes(b'API_KEY=do-not-copy')
        with patch.object(transfer.subprocess,'check_output',side_effect=[('\0'.join(files)+'\0').encode(),b'head\n']):
            result=transfer.create(self.root,self.dialogue,self.archive)
        self.assertEqual(result['files'],3);self.assertEqual(stat.S_IMODE(self.archive.stat().st_mode),0o600)
        restored=self.base/'restored';chat=self.base/'restored-chat'
        self.assertTrue(transfer.inspect_or_restore(self.archive,restored,chat)['restored'])
        self.assertEqual((restored/'data/source.bin').read_bytes(),b'\x00original')
        self.assertEqual((chat/'history.json').read_bytes(),b'{"private":"context"}')
        self.assertFalse((restored/'data/.env').exists());self.assertFalse((chat/'.env.production').exists())
        self.assertEqual(stat.S_IMODE((restored/'data/source.bin').stat().st_mode),0o600)
        self.assertTrue(transfer.inspect_or_restore(self.archive,restored,chat)['verified'])
        with self.assertRaisesRegex(ValueError,'already_exists'):transfer.create(self.root,self.dialogue,self.archive)

    def test_conflict_and_corruption_fail_before_any_write(self):
        self.archive_of({'repository/data/new':b'new','repository/data/existing':b'from-archive'})
        (self.root/'data').mkdir();(self.root/'data/existing').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'overwrite'):transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
        self.assertFalse((self.root/'data/new').exists());self.assertEqual((self.root/'data/existing').read_bytes(),b'keep')
        self.archive_of({'repository/data/new':b'new'},wrong_hash=True)
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
        self.assertFalse((self.root/'data/new').exists())

    def test_scope_traversal_noncanonical_paths_and_env_reject(self):
        for name in ['repository/src/new.py','repository/.codex/config.toml','repository/data/../out',
                     'repository/data//a','repository/data/./a','repository/data/a/',
                     'repository/data/.env.key','repository/.local/elsewhere/a','dialogue/../outside']:
            with self.subTest(name=name):
                self.archive_of({name:b'payload'})
                with self.assertRaises(ValueError):transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_overlapping_destinations_cannot_silently_skip_a_member(self):
        self.archive_of({'repository/data/same':b'one','dialogue/same':b'two'})
        with self.assertRaisesRegex(ValueError,'same_destination'):
            transfer.inspect_or_restore(self.archive,self.root,self.root/'data')
        self.assertFalse((self.root/'data').exists())

    def test_file_directory_collisions_fail_before_any_write(self):
        self.archive_of({'repository/data/first':b'first','repository/data/x':b'file','repository/data/x/child':b'child'})
        with self.assertRaisesRegex(ValueError,'file_directory_conflict'):transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
        self.assertFalse((self.root/'data').exists())
        self.archive_of({'repository/data/first':b'first','repository/data/x/child':b'child'})
        (self.root/'data').mkdir();(self.root/'data/x').write_bytes(b'existing-file')
        with self.assertRaisesRegex(ValueError,'parent_is_not_directory'):transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
        self.assertFalse((self.root/'data/first').exists())

    def test_archive_symlink_and_destination_symlink_reject(self):
        self.archive_of({'repository/data/file':b'payload'},symlink=True)
        with self.assertRaisesRegex(ValueError,'non_file'):transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
        self.archive_of({'repository/data/file':b'payload'})
        (self.root/'data').symlink_to(self.dialogue,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
        self.assertFalse((self.dialogue/'file').exists())

    def test_export_detects_changed_source_and_cleans_partial_archive(self):
        target=self.root/'data/source';target.parent.mkdir();target.write_bytes(b'original')
        original=Path.read_bytes;calls=0
        def changing(path):
            nonlocal calls
            if path==target:
                calls+=1
                return b'first' if calls==1 else b'changed'
            return original(path)
        with patch.object(transfer.subprocess,'check_output',side_effect=[b'data/source\0',b'head\n']),patch.object(Path,'read_bytes',changing):
            with self.assertRaisesRegex(ValueError,'source_changed'):transfer.create(self.root,None,self.archive)
        self.assertFalse(self.archive.exists())

    def test_empty_dialogue_directories_and_every_new_ancestor_restore_privately(self):
        (self.dialogue/'session/turns').mkdir(parents=True)
        (self.dialogue/'session/session.json').write_bytes(b'{"status":"idle"}')
        (self.dialogue/'other-empty').mkdir()
        (self.dialogue/'.env-secret-directory').mkdir()
        source=self.root/'data/deep/source';source.parent.mkdir(parents=True);source.write_bytes(b'source')
        with patch.object(transfer.subprocess,'check_output',side_effect=[b'data/deep/source\0',b'head\n']):
            transfer.create(self.root,self.dialogue,self.archive)
        with tarfile.open(self.archive,'r:gz') as archive:
            manifest=json.load(archive.extractfile('transfer-manifest.json'))
        self.assertTrue({'dialogue','dialogue/session','dialogue/session/turns','dialogue/other-empty'} <= set(manifest['directories']))
        self.assertNotIn('dialogue/.env-secret-directory',manifest['directories'])
        restore_base=self.base/'new/private/nested'
        repository=restore_base/'repo';dialogue=restore_base/'chat'
        result=transfer.inspect_or_restore(self.archive,repository,dialogue)
        self.assertGreater(result['directories'],0)
        self.assertTrue((dialogue/'session/turns').is_dir())
        self.assertEqual(list((dialogue/'session/turns').iterdir()),[])
        self.assertTrue((dialogue/'other-empty').is_dir())
        for directory in [self.base/'new',*(self.base/'new').rglob('*')]:
            if directory.is_dir():self.assertEqual(stat.S_IMODE(directory.stat().st_mode),0o700,str(directory))
        self.assertEqual(stat.S_IMODE((dialogue/'session/session.json').stat().st_mode),0o600)

    def test_legacy_file_only_manifest_creates_private_ancestors_without_chmod_existing(self):
        self.archive_of({'dialogue/session/nested/value':b'value'})
        self.dialogue.chmod(0o755)
        transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
        self.assertEqual(stat.S_IMODE(self.dialogue.stat().st_mode),0o755)
        self.assertEqual(stat.S_IMODE((self.dialogue/'session').stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((self.dialogue/'session/nested').stat().st_mode),0o700)

    def test_directory_manifest_is_validated_before_creating_any_directory(self):
        for directories in [['dialogue/session','dialogue/../outside'],['repository/src'],
                ['dialogue/empty','dialogue/empty'],['dialogue/.env.hidden'],['dialogue/value'],
                ['dialogue/value/child'],['dialogue//empty']]:
            with self.subTest(directories=directories):
                self.archive_of({'dialogue/value':b'value'},directories=directories)
                with self.assertRaises(ValueError):transfer.inspect_or_restore(self.archive,self.root,self.dialogue)
                self.assertEqual(list(self.dialogue.iterdir()),[])
        self.archive_of({},directories=['dialogue/empty'])
        with self.assertRaisesRegex(ValueError,'dialogue_destination_required'):
            transfer.inspect_or_restore(self.archive,self.root)

    def test_missing_explicit_dialogue_is_not_silently_omitted(self):
        with self.assertRaisesRegex(ValueError,'dialogue_directory_missing'):
            transfer.create(self.root,self.base/'missing-chat',self.archive)
        self.assertFalse(self.archive.exists())

    def test_explicit_output_export_verify_restore_keeps_original_bytes_and_scope(self):
        payloads={'output/run-a/history/manifest.json':b'{"absolute_path":"/old/repo/output/run-a"}\n',
                  'output/run-a/turn/input.bin':b'\x00\xffexact bytes',
                  'output/nested/run-b/record.json':b'{"second":true}'}
        for name,raw in {**payloads,'output/not-selected/private.json':b'never include',
                         'output/run-a/.env.production':b'fake key',
                         'output/run-a/.env-dir/secret':b'fake key',
                         'output/run-a/__pycache__/thing.pyc':b'cache'}.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        (self.root/'output/run-a/empty').mkdir()
        with patch.object(transfer.subprocess,'check_output',side_effect=[b'',b'head\n']):
            transfer.create(self.root,None,self.archive,include_output=['output/run-a','output/nested/run-b'])
        with tarfile.open(self.archive,'r:gz') as archive:
            manifest=json.load(archive.extractfile('transfer-manifest.json'))
        self.assertEqual(manifest['schema'],'uteki-private-transfer-v2')
        self.assertEqual(manifest['output_selections'],['output/run-a','output/nested/run-b'])
        self.assertEqual(set(manifest['files']),{'repository/'+name for name in payloads})
        self.assertTrue(transfer.inspect_or_restore(self.archive)['verified'])
        destination=self.base/'empty-new-machine'
        self.assertTrue(transfer.inspect_or_restore(self.archive,destination)['restored'])
        for name,raw in payloads.items():self.assertEqual((destination/name).read_bytes(),raw)
        self.assertTrue((destination/'output/run-a/empty').is_dir())
        self.assertFalse((destination/'output/not-selected').exists())
        self.assertFalse((destination/'output/run-a/.env.production').exists())
        self.assertEqual(stat.S_IMODE((destination/'output/run-a').stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((destination/'output/run-a/turn/input.bin').stat().st_mode),0o600)
        # Identical restore is idempotent; a changed local file prevents all writes.
        transfer.inspect_or_restore(self.archive,destination)
        first=destination/'output/run-a/history/manifest.json';first.unlink()
        changed=destination/'output/nested/run-b/record.json';changed.write_bytes(b'keep local')
        with self.assertRaisesRegex(ValueError,'overwrite'):
            transfer.inspect_or_restore(self.archive,destination)
        self.assertFalse(first.exists());self.assertEqual(changed.read_bytes(),b'keep local')

    def test_default_create_does_not_collect_output_and_retains_v1(self):
        path=self.root/'output/run-a/private';path.parent.mkdir(parents=True);path.write_bytes(b'private')
        with patch.object(transfer.subprocess,'check_output',side_effect=[b'',b'head\n']):
            transfer.create(self.root,None,self.archive)
        with tarfile.open(self.archive,'r:gz') as archive:
            manifest=json.load(archive.extractfile('transfer-manifest.json'))
        self.assertEqual(manifest['schema'],'uteki-private-transfer-v1')
        self.assertNotIn('output_selections',manifest);self.assertEqual(manifest['files'],{})

    def test_explicit_output_selection_rejects_bad_scope_missing_files_and_symlinks(self):
        path=self.root/'output/run-a/file';path.parent.mkdir(parents=True);path.write_bytes(b'file')
        (self.root/'output/link').symlink_to(path.parent,target_is_directory=True)
        for selected in [['output'],['data/run-a'],['output/missing'],['output/run-a/file'],
                         [str(path.parent)],['output/../data'],['output//run-a'],['output/run-a/'],
                         ['output/link'],['output/.env-private'],['output/run-a','output/run-a'],
                         ['output/run-a','output/run-a/child']]:
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):transfer.create(self.root,None,self.archive,selected)
                self.assertFalse(self.archive.exists())
        (path.parent/'linked-file').symlink_to(path)
        with patch.object(transfer.subprocess,'check_output',return_value=b''):
            with self.assertRaisesRegex(ValueError,'symlink'):
                transfer.create(self.root,None,self.archive,['output/run-a'])
        self.assertFalse(self.archive.exists())
        with self.assertRaisesRegex(ValueError,'archive_inside_selected_output'):
            transfer.create(self.root,None,path.parent/'self.tar.gz',['output/run-a'])

    def test_v2_archive_cannot_expand_scope_or_bypass_existing_validations(self):
        valid_dirs=['repository','repository/output','repository/output/run-a']
        for selected in [[],['output'],['output/../data'],['output//run-a'],['data/run-a'],
                         ['output/run-a','output/run-a'],['output/run-a','output/run-a/nested']]:
            with self.subTest(selected=selected):
                self.archive_of({},schema='uteki-private-transfer-v2',output_selections=selected,directories=valid_dirs)
                with self.assertRaises(ValueError):transfer.inspect_or_restore(self.archive,self.root)
                self.assertEqual(list(self.root.iterdir()),[])
        for name in ['repository/output/run-a','repository/output/run-b/file',
                     'repository/output/run-a-other/file','repository/output/run-a/../file',
                     'repository/output/run-a/.env.secret']:
            with self.subTest(name=name):
                self.archive_of({name:b'payload'},schema='uteki-private-transfer-v2',
                                output_selections=['output/run-a'],directories=valid_dirs)
                with self.assertRaises(ValueError):transfer.inspect_or_restore(self.archive,self.root)
                self.assertEqual(list(self.root.iterdir()),[])
        self.archive_of({'repository/output/run-a/file':b'payload'},schema='uteki-private-transfer-v2',
                        output_selections=['output/run-a'],directories=valid_dirs,wrong_hash=True)
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):transfer.inspect_or_restore(self.archive,self.root)
        self.assertEqual(list(self.root.iterdir()),[])
        # A v1 manifest cannot opt itself into the additional scope.
        self.archive_of({'repository/output/run-a/file':b'payload'},output_selections=['output/run-a'])
        with self.assertRaisesRegex(ValueError,'require_v2'):transfer.inspect_or_restore(self.archive)
        self.archive_of({'repository/output/run-a/file':b'payload'})
        with self.assertRaisesRegex(ValueError,'outside_transfer_scope'):transfer.inspect_or_restore(self.archive)

    def test_v2_output_destination_symlink_is_rejected(self):
        self.archive_of({'repository/output/run-a/file':b'payload'},schema='uteki-private-transfer-v2',
                        output_selections=['output/run-a'],directories=['repository/output/run-a'])
        (self.root/'output').symlink_to(self.dialogue,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):transfer.inspect_or_restore(self.archive,self.root)
        self.assertEqual(list(self.dialogue.iterdir()),[])


if __name__=='__main__':unittest.main()

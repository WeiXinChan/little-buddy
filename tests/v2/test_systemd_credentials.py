"""Local synthetic metadata boundaries; real LoadCredential proof is a separate probe."""
from contextlib import ExitStack
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.v2.files import ConfigurationError,read_checked,_systemd_credential,_mount_id


class Credentials(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.key=self.root/'fixture';self.key.write_text(os.urandom(32).hex());self.key.chmod(0o600)

    def rejected(self,path):
        with self.assertRaisesRegex(ConfigurationError,'synthetic_file_invalid'):read_checked(path,'synthetic')

    def test_normal_private_sources_remain_accepted_without_mount_or_environment(self):
        with patch.dict(os.environ,{},clear=False):
            self.assertEqual(len(read_checked(self.key,'synthetic')),64)
        self.key.chmod(0o400);self.root.chmod(0o500)
        self.assertEqual(len(read_checked(self.key,'synthetic')),64)
        self.root.chmod(0o700)

    def test_ordinary_groupread_directory_or_file_rejected_even_with_fake_environment(self):
        self.root.chmod(0o750)
        self.rejected(self.key) # parent group access is not a credential-directory grant
        self.root.chmod(0o700);self.key.chmod(0o440)
        for value in (str(self.root),'/run/credentials/forged.service','/tmp/credentials/forged.service'):
            with patch.dict(os.environ,{'CREDENTIALS_DIRECTORY':value}):self.rejected(self.key)

    def test_leaf_parent_symlink_and_hardlink_rejected(self):
        leaf=self.root/'alias';leaf.symlink_to(self.key);self.rejected(leaf)
        alias=self.root/'parent-alias';alias.symlink_to(self.root,target_is_directory=True)
        self.rejected(alias/'fixture')
        hard=self.root/'hard';os.link(self.key,hard);self.rejected(self.key)

    def test_size_type_and_nonsecret_rules_unchanged(self):
        with self.assertRaises(ConfigurationError):read_checked(self.key,'synthetic',limit=1)
        directory=self.root/'directory';directory.mkdir();self.rejected(directory)
        self.key.chmod(0o644)
        self.assertEqual(len(read_checked(self.key,'public',secret=False)),64)
        self.key.chmod(0o664)
        with self.assertRaises(ConfigurationError):read_checked(self.key,'public',secret=False)

    def metadata(self):
        d=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY);f=os.open(self.key,os.O_RDONLY)
        self.addCleanup(os.close,d);self.addCleanup(os.close,f)
        real=os.fstat(d)
        parent=SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFDIR|0o550,st_dev=real.st_dev,st_ino=real.st_ino)
        info=SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFREG|0o440)
        return Path('/run/credentials/fixture.service/fixture'),d,f,parent,info

    def anchors(self,d,parent):
        # Only to reach each kernel-fd gate in isolation. This is not a fake
        # read-only success; all successful exceptions are proven by real systemd.
        stack=ExitStack()
        stack.enter_context(patch('backend.v2.files.os.geteuid',return_value=1000))
        stack.enter_context(patch.dict(os.environ,{'CREDENTIALS_DIRECTORY':'/run/credentials/fixture.service'}))
        stack.enter_context(patch('backend.v2.files.os.open',side_effect=lambda *a,**kw:os.dup(d)))
        stack.enter_context(patch('backend.v2.files.os.fstat',return_value=parent))
        return stack

    def test_writable_filesystem_rejected_despite_spoofed_path_and_root_metadata(self):
        path,d,f,parent,info=self.metadata()
        self.assertFalse(os.fstatvfs(d).f_flag&os.ST_RDONLY)
        with self.anchors(d,parent):self.assertFalse(_systemd_credential(path,d,f,parent,info))

    def test_descriptor_mount_identity_mismatch_is_not_accepted(self):
        path,d,f,parent,info=self.metadata()
        with self.anchors(d,parent),patch('backend.v2.files._mount_id',side_effect=[100,100,101]):
            self.assertFalse(_systemd_credential(path,d,f,parent,info))
        self.assertGreater(_mount_id(d),0)

    def test_exact_root_mode_gid_path_and_root_caller_constraints(self):
        path,d,f,parent,info=self.metadata()
        for target,field,value in ((parent,'st_gid',65500),(info,'st_gid',65500),
                                   (parent,'st_mode',stat.S_IFDIR|0o570),(info,'st_mode',stat.S_IFREG|0o444),
                                   (info,'st_uid',65500)):
            old=getattr(target,field);setattr(target,field,value)
            with patch.dict(os.environ,{'CREDENTIALS_DIRECTORY':str(path.parent)}):
                self.assertFalse(_systemd_credential(path,d,f,parent,info))
            setattr(target,field,old)
        with patch.dict(os.environ,{'CREDENTIALS_DIRECTORY':str(path.parent)}),patch('os.geteuid',return_value=0):
            self.assertFalse(_systemd_credential(path,d,f,parent,info))
        with patch.dict(os.environ,{'CREDENTIALS_DIRECTORY':str(path.parent)+'/' }):
            self.assertFalse(_systemd_credential(path,d,f,parent,info))

    def test_missing_proc_or_untrusted_anchor_fails_closed(self):
        path,d,f,parent,info=self.metadata()
        with self.anchors(d,parent),patch('backend.v2.files._mount_id',side_effect=OSError('synthetic')):
            self.assertFalse(_systemd_credential(path,d,f,parent,info))
        with patch.dict(os.environ,{'CREDENTIALS_DIRECTORY':str(path.parent)}),patch('os.open',side_effect=OSError('no anchor')):
            self.assertFalse(_systemd_credential(path,d,f,parent,info))

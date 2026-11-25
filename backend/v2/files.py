"""Bounded Linux credential reads with stable, content-free errors."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import ctypes
import re


def disable_core_dumps():
    if ctypes.CDLL(None,use_errno=True).prctl(4,0,0,0,0)!=0:
        raise ConfigurationError('core_dump_protection_failed')


class ConfigurationError(ValueError):
    pass


def _mount_id(fd):
    with open('/proc/self/fdinfo/'+str(fd),'rb') as stream:
        lines=stream.read(4097)
    if len(lines)>4096:raise ValueError()
    values=[line.split()[1] for line in lines.splitlines() if line.startswith(b'mnt_id:')]
    if len(values)!=1 or not values[0].isdigit():raise ValueError()
    return int(values[0])


def _systemd_credential(path,directory,descriptor,parent,info):
    """Narrow system-service exception, not an environment-based permission grant.

    Require the opened descriptors to identify a root-protected /run/credentials
    mount, not just a path named by the caller. Ordinary sources retain private
    modes. No assumption is made about ACLs or the dynamic process's group.
    """
    anchors=[]
    try:
        candidate=os.environ.get('CREDENTIALS_DIRECTORY','')
        if (os.geteuid()==0 or not path.is_absolute() or candidate!=str(path.parent) or
            path.parent.parent!=Path('/run/credentials') or
            not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service',path.parent.name) or
            parent.st_uid!=0 or parent.st_gid!=0 or stat.S_IMODE(parent.st_mode)!=0o550 or
            info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=0o440):return False
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        anchor=os.open('/run',flags);anchors.append(anchor)
        for component in ('credentials',path.parent.name):
            root=os.fstat(anchor)
            if root.st_uid!=0 or root.st_gid!=0 or root.st_mode&0o022:return False
            anchor=os.open(component,flags,dir_fd=anchor);anchors.append(anchor)
        controlled=os.fstat(anchor)
        if (controlled.st_dev,controlled.st_ino)!=(parent.st_dev,parent.st_ino):return False
        mount_id=_mount_id(directory)
        if _mount_id(anchor)!=mount_id or _mount_id(descriptor)!=mount_id:return False
        if any(not os.fstatvfs(fd).f_flag&os.ST_RDONLY for fd in (anchor,directory,descriptor)):return False
        with open('/proc/self/mountinfo','rb') as stream:table=stream.read(4*1024*1024+1)
        if len(table)>4*1024*1024:return False
        for line in table.splitlines():
            fields=line.split()
            if not fields or fields[0]!=str(mount_id).encode():continue
            split=fields.index(b'-')
            return (fields[4]==candidate.encode('ascii') and b'ro' in fields[5].split(b',') and
                    fields[split+1] in {b'tmpfs',b'ramfs'})
        return False
    except (OSError,ValueError,TypeError,IndexError,UnicodeError):return False
    finally:
        for fd in reversed(anchors):os.close(fd)


@contextmanager
def checked_file(path, role, *, secret=True, limit=65536):
    directory=descriptor=None
    try:
        path=Path(path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        parent=os.fstat(directory)
        if parent.st_uid not in {0,os.geteuid()} or parent.st_mode&0o022:raise ValueError()
        descriptor=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=directory)
        info=os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=limit or
            info.st_uid not in {0,os.geteuid()} or (not secret and info.st_mode&0o022)):
            raise ValueError()
        if secret and (parent.st_mode&0o077 or info.st_mode&0o077):
            if not _systemd_credential(path,directory,descriptor,parent,info):raise ValueError()
    except (OSError,ValueError,TypeError):
        if descriptor is not None:os.close(descriptor)
        if directory is not None:os.close(directory)
        raise ConfigurationError(role+'_file_invalid') from None
    try:yield descriptor
    finally:os.close(descriptor);os.close(directory)


def read_checked(path,role,*,secret=True,limit=65536):
    with checked_file(path,role,secret=secret,limit=limit) as fd:
        before=os.fstat(fd)
        content=os.read(fd,limit+1)
        after=os.fstat(fd)
        if (len(content)!=before.st_size or len(content)>limit or
            (before.st_mtime_ns,before.st_ctime_ns)!=(after.st_mtime_ns,after.st_ctime_ns)):
            raise ConfigurationError(role+'_file_changed')
        try:return content.decode('utf-8')
        except UnicodeError:raise ConfigurationError(role+'_encoding_invalid') from None

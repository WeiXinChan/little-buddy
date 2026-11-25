"""Bounded Linux credential reads with stable, content-free errors."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import ctypes


def disable_core_dumps():
    if ctypes.CDLL(None,use_errno=True).prctl(4,0,0,0,0)!=0:
        raise ConfigurationError('core_dump_protection_failed')


class ConfigurationError(ValueError):
    pass


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
            info.st_uid not in {0,os.geteuid()} or info.st_mode&(0o077 if secret else 0o022)):
            raise ValueError()
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

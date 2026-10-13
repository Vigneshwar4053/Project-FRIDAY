"""Selected inert UTF-8 files only; no directory walk, URL fetch or runtime hooks."""
import os
from pathlib import Path
import re
import stat
import unicodedata
from friday.tools.grants import directory_descriptor, lexical_path
from friday.tools.sensitive import SensitivePaths
from friday.intelligence.models import KnowledgeError, MAX_DOCUMENT_BYTES, fingerprint
from friday.intelligence.permissions import AuthorizationRequest, KnowledgePurpose, KnowledgeAuthorizationDenied

_SECRET = re.compile(r'(?i)(?:password|passphrase|api[_ -]?key|access[_ -]?token|'
    r'refresh[_ -]?token|client[_ -]?secret|aws_secret_access_key)\s*[=:]\s*\S+')


def reject_secrets(text):
    if SensitivePaths.excluded_content(text.encode('utf-8')) or _SECRET.search(text):
        raise KnowledgeError('Document or metadata is excluded by privacy policy.')


def normalize_text(text):
    if type(text) is not str:
        raise KnowledgeError('Document must contain UTF-8 text.')
    try:
        if len(text.encode('utf-8'))>MAX_DOCUMENT_BYTES:raise KnowledgeError('Document exceeds the byte limit.')
        reject_secrets(text)
        text=unicodedata.normalize('NFC',text.removeprefix('\ufeff').replace('\r\n','\n').replace('\r','\n'))
        if (not text.strip() or len(text.encode('utf-8'))>MAX_DOCUMENT_BYTES or
                any((ord(c)<32 and c not in '\n\t') or 127<=ord(c)<=159 for c in text)):
            raise KnowledgeError('Document is empty or contains unsupported controls.')
        return text
    except UnicodeError:
        raise KnowledgeError('Document must contain valid UTF-8 text.') from None


def read_text_file(path, authorization, *, sensitive=None):
    """Pins exact identity before approval; returns text, never retention consent.

    This function is not wired to the runtime and is tested only on synthetic files.
    The host must add its private storage paths to the injected SensitivePaths.
    """
    path=lexical_path(str(path))
    sensitive=sensitive or SensitivePaths()
    if (not path.is_absolute() or path.suffix not in {'.txt','.md'} or sensitive.excluded(path) or
            path.parts[1] in {'etc','proc','sys','dev','usr','root','run'}):
        raise KnowledgeError('Document path is outside the supported ingestion policy.')
    try:
        with directory_descriptor(path.parent) as parent:
            fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent)
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_DOCUMENT_BYTES:
                    raise KnowledgeError('Document identity or size is unsupported.')
                identity=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
                authorization.require(AuthorizationRequest(KnowledgePurpose.READ_DOCUMENT,(str(path),),
                    fingerprint([str(path),identity])))
                for current in (os.fstat(fd),os.stat(path.name,dir_fd=parent,follow_symlinks=False)):
                    if (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns,current.st_ctime_ns)!=identity:
                        raise KnowledgeError('Document changed during approval.')
                data=bytearray()
                while len(data)<=MAX_DOCUMENT_BYTES:
                    block=os.read(fd,min(65536,MAX_DOCUMENT_BYTES+1-len(data)))
                    if not block:break
                    data.extend(block)
                after=os.fstat(fd);entry=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
                for current in (after,entry):
                    if (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns,current.st_ctime_ns)!=identity:
                        raise KnowledgeError('Document changed during approved reading.')
                if sensitive.excluded_content(data):raise KnowledgeError('Document is excluded by privacy policy.')
                return normalize_text(data.decode('utf-8',errors='strict'))
            finally:os.close(fd)
    except KnowledgeAuthorizationDenied:raise
    except (OSError,UnicodeError,ValueError):
        raise KnowledgeError('Selected document is unavailable or malformed.') from None

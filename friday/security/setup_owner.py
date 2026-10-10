"""Owner-run credential setup: python -B -m friday.security.setup_owner.

Never run this command automatically or accept a secret in argv/environment.
Existing .env updates require the owner's explicit --update-existing option.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from friday.security.owner import (Argon2Provider, ENABLED, HASH, MAX_CONFIG_BYTES,
                                   OwnerAuthenticationError, hidden_secret, private_config, validate_hash)
from friday.tools.grants import directory_descriptor


def excluded_from_git(root):
    options = dict(cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=5, check=False)
    # Check both ignore rules and the index; ignored but tracked is not private.
    return (subprocess.run(['/usr/bin/git','check-ignore','--no-index','-q','--','.env'], **options).returncode == 0 and
            subprocess.run(['/usr/bin/git','ls-files','--error-unmatch','--','.env'], **options).returncode == 1)


def setup(root, *, update_existing=False, reader=hidden_secret, provider_factory=Argon2Provider):
    root = Path(root).absolute()
    path = root / '.env'
    if not excluded_from_git(root):
        raise OwnerAuthenticationError('.env must be excluded from Git and untracked before owner setup.')
    provider = provider_factory()  # Dependency check before requesting a secret.
    original = ''
    identity = None
    if os.path.lexists(path):
        if not update_existing:
            raise OwnerAuthenticationError('Existing .env was not changed. Explicit --update-existing authorization is required.')
        original, identity = private_config(path)
    secret = confirmation = None
    try:
        secret = reader('Create owner security passphrase (hidden, at least 12 characters): ')
        confirmation = reader('Confirm owner security passphrase (hidden): ')
        if type(secret) is not str or not 12 <= len(secret) <= 1024 or '\x00' in secret or secret != confirmation:
            raise OwnerAuthenticationError('Passphrase confirmation failed or passphrase length is invalid; nothing changed.')
        encoded = validate_hash(provider.hash(secret))
    finally:
        secret = confirmation = None
    kept = [line for line in original.splitlines() if line.strip().partition('=')[0] not in {ENABLED, HASH}]
    content = ('\n'.join([*kept, ENABLED+'=true', HASH+'='+encoded])+'\n').encode('utf-8')
    if len(content) > MAX_CONFIG_BYTES:
        raise OwnerAuthenticationError('Credential configuration would exceed its size limit; nothing changed.')
    with directory_descriptor(root) as directory:
        if identity is None:
            fd = os.open('.env', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600, dir_fd=directory)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content);stream.flush();os.fsync(stream.fileno())
        else:
            name = '.env.owner-'+uuid4().hex
            try:
                fd = os.open(name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600, dir_fd=directory)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content);stream.flush();os.fsync(stream.fileno())
                _, current = private_config(path)
                if current != identity:
                    raise OwnerAuthenticationError('Credential configuration changed during setup; update refused.')
                os.replace(name, '.env', src_dir_fd=directory, dst_dir_fd=directory)
            finally:
                try: os.unlink(name,dir_fd=directory)
                except FileNotFoundError: pass
        os.fsync(directory)


def main():
    parser = argparse.ArgumentParser(description='Set up local owner authentication using hidden terminal input.')
    parser.add_argument('--update-existing',action='store_true',help='Explicitly authorize replacing owner-auth keys in an existing private .env.')
    args = parser.parse_args()
    try:
        setup(Path(__file__).absolute().parents[2],update_existing=args.update_existing)
    except (Exception, KeyboardInterrupt):
        # Configuration contents, input values and library errors never escape.
        print('Owner setup failed or cancelled. Check Argon2 availability, Git exclusion, and owner-only .env permissions. No secret was printed.',file=sys.stderr)
        return 1
    print('Owner authentication configured. Only the salted Argon2id hash was stored; existing capability and permission restrictions still apply.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

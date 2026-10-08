"""Conservative name/path exclusions, enforced independently of read grants."""
from pathlib import Path
import re

_PRIVATE_COMPONENTS = frozenset({
    '.ssh', '.gnupg', '.aws', '.kube', '.mozilla', '.pki', '.git', '.azure',
    'secrets', 'keyrings', 'gnupg', 'google-chrome', 'chromium',
    'brave-browser', 'microsoft-edge', 'vivaldi', 'firefox',
    'bitwarden', '.bitwarden', '1password', '.1password', 'keepassxc', '.password-store',
})
_PRIVATE_PAIRS = frozenset({('.config', 'gh'), ('.config', 'gcloud'),
                            ('.config', 'op'), ('.docker', 'config.json')})
_PRIVATE_NAMES = frozenset({'id_rsa', 'id_ed25519', 'id_dsa', 'id_ecdsa',
    'authorized_keys', 'private_key', 'private-key', 'credentials', 'credentials.json',
    'credentials.yaml', 'credentials.yml', 'credentials.ini', 'credentials.toml',
    'login data', 'cookies', 'logins.json', 'key4.db', 'key3.db', 'signons.sqlite',
    '.netrc', '.npmrc', '.pypirc', '.git-credentials', '.dockerconfigjson',
    'kubeconfig', 'permissions.json', 'grants.json'})
_PRIVATE_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.ppk', '.kdb', '.kdbx',
                     '.psafe3', '.opvault', '.agilekeychain')
_PRIVATE_KEY = re.compile(rb'-----BEGIN (?:(?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----')
_PRIVATE_JSON = re.compile(rb'"(?:access_token|refresh_token|client_secret|private_key|aws_secret_access_key)"\s*:\s*"[^"]+', re.IGNORECASE)


class SensitivePaths:
    def __init__(self, protected_paths=()):
        self.protected_paths = tuple(Path(p).expanduser().resolve(strict=False) for p in protected_paths)

    def excluded(self, path):
        path = Path(path)
        parts = tuple(part.casefold() for part in path.parts)
        if any(part in _PRIVATE_COMPONENTS for part in parts):
            return True
        if any(pair in _PRIVATE_PAIRS for pair in zip(parts, parts[1:])):
            return True
        for part in parts:
            if (part in _PRIVATE_NAMES or part == '.env' or part.startswith('.env.') or
                part.startswith('credentials.') or
                part.endswith(_PRIVATE_SUFFIXES) or
                re.fullmatch(r'(?:private[_-]?keys?|api[_-]?keys?|client[_-]?secrets?|secret[_-]?keys?)(?:\..*)?', part) or
                re.fullmatch(r'.*firebase[-_]adminsdk.*\.json', part) or
                re.fullmatch(r'(?:.*[_-]|\.)?(?:access[_-]?|refresh[_-]?)?tokens?(?:[._-].*)?', part) or
                re.fullmatch(r'(?:service[_-]?account|service[_-]?account[_-]?key)(?:\..*)?', part)):
                return True
        return any(path == protected or path.is_relative_to(protected)
                   for protected in self.protected_paths)

    @staticmethod
    def excluded_content(content):
        # Catch private-key blobs even when their filename is innocuous.
        return bool(_PRIVATE_KEY.search(content) or _PRIVATE_JSON.search(content))

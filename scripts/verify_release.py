"""Check the published files against their release SHA-256 identities."""
from pathlib import Path
import hashlib
import json
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'docs/release_manifest.json').read_text())
    failures = []
    for item in manifest['files']:
        path = root / item['path']
        if not path.resolve().is_relative_to(root.resolve()):
            failures.append(f"Unsafe manifest path: {item['path']}")
        elif not path.is_file():
            failures.append(f"Missing: {item['path']}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            failures.append(f"Changed: {item['path']}")
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        return 1
    print(f"Verified {len(manifest['files'])} published file identities.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Select a published upstream revision; fetching/testing/deployment are separate."""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parent
REPOSITORY = 'beliavsky/python-to-fortran'


def select_revision(pin_path, revision='', token='', opener=urllib.request.urlopen):
    if revision and not re.fullmatch(r'[0-9a-fA-F]{40}', revision):
        raise ValueError('Revision must be a full published commit SHA (or blank for latest main).')
    pin = json.loads(pin_path.read_text(encoding='utf-8'))
    if pin.get('repository') != REPOSITORY:
        raise ValueError('Unexpected upstream repository')
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPOSITORY}/commits/{revision or "main"}',
        headers={'User-Agent': 'p2f-playground-updater', 'Accept': 'application/vnd.github+json',
                 **({'Authorization': f'Bearer {token}'} if token else {})},
    )
    with opener(request, timeout=60) as response:
        sha = json.load(response).get('sha', '')
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('GitHub did not return a complete commit SHA')
    if revision and sha != revision.lower():
        raise ValueError('GitHub returned a different revision')
    changed = pin.get('commit') != sha
    if changed:
        pin['commit'] = sha
        pin_path.write_text(json.dumps(pin, indent=2) + '\n', encoding='utf-8')
    return sha, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', default='', help='full published SHA; default: latest main')
    args = parser.parse_args()
    sha, changed = select_revision(ROOT / 'upstream.json', args.commit,
                                   os.environ.get('GITHUB_TOKEN', ''))
    print(f'Selected published p2f revision {sha}' + (' (pin updated)' if changed else ' (already pinned)'))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a', encoding='utf-8') as stream:
            stream.write(f'commit={sha}\nchanged={str(changed).lower()}\n')


if __name__ == '__main__':
    main()

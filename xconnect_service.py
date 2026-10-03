"""Check a deployed Modal API and configure the GitHub Pages execution page."""
import argparse
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='HTTPS origin printed by modal deploy xmodal.py')
    args = parser.parse_args()
    url = args.url.rstrip('/')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.modal.run') or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        parser.error('Expected the HTTPS origin of the deployed Modal service (no /api suffix).')
    with urllib.request.urlopen(url + '/api/health', timeout=120) as response:
        health = json.load(response)
    pin = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
    if health.get('commit') != pin['commit'] or health.get('sandbox') != 'gvisor' or health.get('network') is not False:
        parser.exit(1, 'Service revision or isolation configuration does not match. Redeploy xmodal.py.\n')
    path = ROOT / 'site/run/service.json'
    path.write_text(json.dumps({'url': url}, indent=2) + '\n', encoding='utf-8')
    print('Connected service configuration:', url)
    print('Commit site\\run\\service.json and push to update the GitHub Pages execution page.')


if __name__ == '__main__':
    main()

"""Build the Pages artifact with content-versioned browser asset URLs."""
import hashlib
from pathlib import Path
import re
import shutil


ASSET_SUFFIXES = {".mjs", ".js", ".css", ".py"}
QUOTED_URL = re.compile(r"(?P<quote>['\"])(?P<url>[^'\"\s]+)(?P=quote)")


def build_site(source: Path, destination: Path) -> str:
    # Include paths as well as contents; a renamed or changed dependency must
    # invalidate its importers too. Runtime ZIPs retain their own integrity check.
    files = sorted(p for p in source.rglob("*") if p.is_file()
                   and p.suffix in ASSET_SUFFIXES | {".html"})
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    version = digest.hexdigest()[:16]
    shutil.copytree(source, destination, dirs_exist_ok=True)
    for path in files:
        if path.suffix not in {".html", ".mjs"}:
            continue

        def stamp(match):
            url = match["url"]
            if ":" in url or url.startswith(("/", "#")) or "?" in url:
                return match[0]
            target = (path.parent / url).resolve()
            if (target.is_relative_to(source.resolve()) and target.is_file()
                    and target.suffix in ASSET_SUFFIXES):
                return f'{match["quote"]}{url}?v={version}{match["quote"]}'
            return match[0]

        (destination / path.relative_to(source)).write_text(
            QUOTED_URL.sub(stamp, path.read_text(encoding="utf-8")), encoding="utf-8")
    return version


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    print("Built _site with asset version", build_site(root / "site", root / "_site"))

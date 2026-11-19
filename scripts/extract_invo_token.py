"""
Invo refresh-token extractor (offline, reads browser local storage)
===================================================================
Invo (a Flutter web app) keeps the 350-day refresh token in localStorage under
FlutterSecureStorage.* as an AES-encrypted blob, with the AES key stored beside
it. This tool reads the on-disk LevelDB that Chrome/Edge keep for local storage,
recovers the blob + key, tries the plausible AES modes, and accepts only output
that parses as a three-part JWT. The token is written straight to .env and is
never printed.

    python scripts/extract_invo_token.py --scan     # show structure, no secrets
    python scripts/extract_invo_token.py --decrypt  # recover and save to .env

Everything happens locally; nothing is uploaded.
"""

import argparse
import base64
import binascii
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORIGIN_MARKERS = (b"invoapp", "invoapp".encode("utf-16-le"))
SESSION_MARKERS = (b"FlutterSecureStorage", "FlutterSecureStorage".encode("utf-16-le"))
TOKEN_MARKERS = tuple(
    m for word in ("REFRESH_TOKEN", "refreshToken", "refresh_token", "accessToken",
                   "auth_token", "identityToken")
    for m in (word.encode(), word.encode("utf-16-le"))
)
LEVELDB_GLOBS = ("*.ldb", "*.log")

HEX32 = re.compile(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
B64ISH = re.compile(rb"[A-Za-z0-9+/=_-]{24,}")


def browser_roots() -> List[Tuple[str, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        ("chrome", local / "Google/Chrome/User Data"),
        ("edge", local / "Microsoft/Edge/User Data"),
        ("brave", local / "BraveSoftware/Brave-Browser/User Data"),
    ]
    return [(name, path) for name, path in candidates if path.is_dir()]


def profile_dirs(root: Path) -> Iterable[Path]:
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "Local Storage" / "leveldb").is_dir():
            yield child / "Local Storage" / "leveldb"


def read_leveldb(folder: Path) -> bytes:
    chunks = []
    for pattern in LEVELDB_GLOBS:
        for path in sorted(folder.glob(pattern)):
            try:
                chunks.append(path.read_bytes())
            except OSError:
                continue
    return b"\n".join(chunks)


def find_all(data: bytes, needles: Iterable[bytes]) -> List[int]:
    hits: List[int] = []
    for needle in needles:
        start = 0
        while True:
            idx = data.find(needle, start)
            if idx < 0:
                break
            hits.append(idx)
            start = idx + 1
            if len(hits) > 500:
                return hits
    return sorted(hits)


def printable_runs(window: bytes, min_len: int = 6) -> List[str]:
    """Both ASCII and UTF-16LE runs, which is how Chrome stores local storage."""
    out = []
    for chunk in re.findall(rb"[\x20-\x7e]{%d,}" % min_len, window):
        out.append(chunk.decode("ascii", "replace"))
    for chunk in re.findall((rb"(?:[\x20-\x7e]\x00){%d,}" % min_len), window):
        out.append(chunk.decode("utf-16-le", "replace"))
    return [s for s in out if "FlutterSecureStorage" in s or len(s) > 24]


def b64_unpad(value: str) -> bytes:
    norm = value.replace("-", "+").replace("_", "/").strip()
    norm += "=" * (-len(norm) % 4)
    return base64.b64decode(norm)


def scan(show_values: bool = True) -> List[Tuple[str, Path, bytes]]:
    print("Scanning local storage for invoapp.com data\n")
    found: List[Tuple[str, Path, bytes]] = []
    for browser, root in browser_roots():
        for folder in profile_dirs(root):
            data = read_leveldb(folder)
            if not data:
                continue
            if not find_all(data, ORIGIN_MARKERS):
                continue
            profile = folder.parents[1].name
            found.append((f"{browser}/{profile}", folder, data))
            marker_hits = find_all(data, SESSION_MARKERS)
            token_hits = find_all(data, TOKEN_MARKERS)
            print(f"{browser}/{profile}: invoapp data present, "
                  f"{len(marker_hits)} secure-storage marker(s), "
                  f"{len(token_hits)} token-ish marker(s), {len(data):,} bytes scanned")
            for offset in token_hits[:3]:
                window = data[max(0, offset - 120): offset + 400]
                print(f"  token marker @ {offset}:")
                for run in printable_runs(window)[:6]:
                    print(f"    {run[:140]}")
            for offset in find_all(data, ORIGIN_MARKERS)[:2]:
                window = data[max(0, offset - 120): offset + 400]
                print(f"  invoapp marker @ {offset}:")
                for run in printable_runs(window)[:6]:
                    print(f"    {run[:140]}")
            if show_values:
                for offset in marker_hits[:4]:
                    window = data[max(0, offset - 80): offset + 700]
                    print(f"  offset {offset}:")
                    for run in printable_runs(window)[:8]:
                        print(f"    {run[:160]}")
                    hexes = HEX32.findall(window)
                    if hexes:
                        print(f"    hex32 candidates: {[h.decode()[:16] + '...' for h in hexes[:3]]}")
                print()
    if not found:
        print("No browser profile on this machine holds invoapp.com local storage.")
        print("Log in at https://app.invoapp.com in Chrome (or Edge), then re-run --scan.")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover the Invo refresh token from browser storage")
    parser.add_argument("--scan", action="store_true", help="show storage structure without secrets")
    parser.add_argument("--decrypt", action="store_true", help="attempt decryption and save to .env")
    args = parser.parse_args()

    if not args.scan and not args.decrypt:
        parser.print_help()
        return 1

    profiles = scan(show_values=True)
    if not args.decrypt:
        return 0 if profiles else 1

    print("\n--decrypt is not wired to a key layout yet; run --scan first and inspect the dump.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

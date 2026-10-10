"""HTTP JSON fetching with retries, plus record/replay of raw responses.

FLUP_RECORD=dir   save every raw response there (with an index.json)
FLUP_REPLAY=dir   read responses from a saved folder instead of the network

Replay is what makes it possible to develop and test offline against real
data captured by GitHub's runners.
"""

import gzip
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "flup-dashboard (personal fantasy dashboard)"


class FetchError(RuntimeError):
    pass


_replay = None
_record_index = []


def _replay_map():
    global _replay
    folder = os.environ.get("FLUP_REPLAY")
    if not folder:
        return None
    if _replay is None:
        root = Path(folder)
        index = json.loads((root / "index.json").read_text())
        _replay = {f["url"]: root / f["file"] for f in index["files"]}
    return _replay


def _download(url, retries=3):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.read()
        except HTTPError as err:
            if err.code < 500 or attempt == retries:
                raise FetchError(f"{url} answered HTTP {err.code}") from err
        except (URLError, TimeoutError) as err:
            if attempt == retries:
                raise FetchError(f"could not reach {url} ({err})") from err
        time.sleep(2 * attempt)


def _record(url, raw):
    folder = os.environ.get("FLUP_RECORD")
    if not folder:
        return
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    name = f"r{len(_record_index):03d}.json.gz"
    (root / name).write_bytes(gzip.compress(raw))
    _record_index.append({"file": name, "url": url, "status": 200, "bytes": len(raw)})
    (root / "index.json").write_text(json.dumps({"files": _record_index}, indent=1))


def get_json(url):
    replay = _replay_map()
    if replay is not None:
        path = replay.get(url)
        if path is None:
            raise FetchError(f"not in the replay snapshot: {url}")
        raw = path.read_bytes()
        if path.suffix == ".gz":
            raw = gzip.decompress(raw)
    else:
        raw = _download(url)
        _record(url, raw)
    try:
        return json.loads(raw)
    except ValueError as err:
        raise FetchError(f"{url} did not return JSON") from err

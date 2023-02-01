"""update.py"""
# pylint: disable=C0103 # Constant name "description" doesn't conform to UPPER_CASE naming style (invalid-name)
# pylint: disable=W0703 # Catching too general exception Exception (broad-except)

import codecs
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import typing as T
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from traceback import print_exc

import requests
from dateutil.parser import parse as parsedate

CACHE_DIR = "cache"
NOTES = "If this application is useful to you, please consider donating to NirSoft - https://www.nirsoft.net/donate.html"
PADLINKS_URL = "https://www.nirsoft.net/pad/pad-links.txt"
REFERER = "https://www.nirsoft.net/"
# 10 seconds per request could cause each run to take about 2h 45m, but if we get caching working, it should only take <50m on average.
SECONDS_BETWEEN_REQUESTS = 10
SI_HEADERS = {"Referer": "https://github.com/ScoopInstaller/Nirsoft"}

HEADERS = {"Referer": REFERER}


def pause_between_requests() -> None:
    """pause_between_requests"""
    if os.environ.get("CI", False):
        time.sleep(SECONDS_BETWEEN_REQUESTS)


def is_newer(url: str, filename: str) -> bool:
    """is_newer"""
    if not os.path.isfile(filename):
        return True
    req = requests.head(url, headers=HEADERS, timeout=60)
    pause_between_requests()
    url_time = req.headers["last-modified"]
    url_dt = parsedate(url_time)
    url_mtime = url_dt.timestamp()
    file_mtime = os.path.getmtime(filename)
    return url_mtime > file_mtime


def load(filename: str) -> bytes:
    """load"""
    print(f"Loading {filename}", end="")
    with io.open(filename, "rb") as fh:
        data = fh.read()
        print(f" ({len(data)} bytes)")
        return data


def save(filename: str, data: bytes) -> None:
    """save"""
    print(f"Saving {filename} ({len(data)} bytes)")
    with io.open(filename, "wb") as fh:
        fh.write(data)


def get_zip_data(url: str, filename: str) -> bytes:
    """get_zip_data"""
    if is_newer(url, filename):
        data = get(url)
        save(filename, data)
    else:
        data = load(filename)
    return data


def get(url: str) -> bytes:
    """get"""
    print(f"Downloading {url}...")
    req = requests.get(url, headers=HEADERS, timeout=60)
    pause_between_requests()
    req.raise_for_status()
    return req.content


def probe_for_exe(data: bytes) -> str:
    """probe_for_exe"""
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            for filename in z.namelist():
                if filename.endswith(".exe"):
                    return filename
    except zipfile.BadZipFile as exc:
        encoded = codecs.encode(data[:2], "hex")
        print(f"{exc}: expected 504b, found {encoded!r}:")
        utf8 = data.decode("utf-8", "backslashreplace")
        print(utf8[:256])

    return ""


def sha256sum(data: bytes) -> str:
    """sha256sum"""
    sha256 = hashlib.sha256()
    sha256.update(data)
    return sha256.hexdigest()


def run(cmd: str) -> int:
    """run"""
    print(f"Running: {cmd}")
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:  # nosec
        (_out, _err) = process.communicate()
        rv = process.wait()
        out = _out.decode("utf-8", "backslashreplace")
        err = _err.decode("utf-8", "backslashreplace")
    print("rv=%d", rv)
    print(out)
    print(err)
    return rv


def main() -> int:
    """main"""
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    print(f"Fetching {PADLINKS_URL}")
    req = requests.get(PADLINKS_URL, headers=SI_HEADERS, timeout=60)
    pause_between_requests()
    req.raise_for_status()
    pads = req.text

    if os.environ.get("CI", False):
        print(f"Sleeping {SECONDS_BETWEEN_REQUESTS} seconds between requests")

    pad_lines = len(pads.splitlines())

    i = 0
    for line in pads.splitlines():
        i += 1
        print("")
        print(f"Generating from {line} ({i}/{pad_lines})")
        try:
            do_padfile(line)
        except Exception:
            print_exc()

    print(f"Processed {pad_lines} manifests")

    # handled now by GitHub action:
    # cmd = "pwsh -Command ./bin/checkver.ps1 -f"
    # print(f"Running {cmd}")
    # run(cmd)
    # cmd = "pwsh -Command ./bin/formatjson.ps1"
    # print(f"Running {cmd}")
    # run(cmd)
    return 0


# @TODO(rasa) rewrite this to use a dataclass
# pylint: disable=R0912 # Too many branches (17/12) (too-many-branches)
# pylint: disable=R0914 # Too many local variables (34/15) (too-many-locals)
# pylint: disable=R0915 # Too many statements (88/50) (too-many-statements)
def do_padfile(line: str) -> bool:
    """do_padfile"""

    version = ""
    full_name = ""
    website = ""
    download = ""
    description = ""

    req = requests.get(line, headers=SI_HEADERS, timeout=60)
    pause_between_requests()
    req.raise_for_status()
    padfile = req.text
    root = ET.fromstring(padfile)

    try:
        info = root.find("Program_Info")
    except Exception:
        pass
    try:
        version = str(info.find("Program_Version").text)  # type: ignore
    except Exception:
        pass
    try:
        full_name = str(info.find("Program_Name").text)  # type: ignore
    except Exception:
        pass
    web_info = root.find("Web_Info")
    try:
        website = str(web_info.find("Application_URLs").find("Application_Info_URL").text)  # type: ignore
    except Exception:
        pass
    website = website.replace("http:", "https:")
    try:
        download = str(web_info.find("Download_URLs").find("Primary_Download_URL").text)  # type: ignore
    except Exception:
        pass
    try:
        descriptions = root.find("Program_Descriptions").find("English")  # type: ignore
        description = descriptions.find("Char_Desc_80").text  # type: ignore
    except AttributeError:
        description = ""

    download = download.replace("http:", "https:")
    zip32 = os.path.basename(download)
    zippath = os.path.join(CACHE_DIR, zip32)

    download64 = download.replace(".zip", "-x64.zip")
    zip64 = os.path.basename(download64)
    zippath64 = os.path.join(CACHE_DIR, zip64)

    name = os.path.splitext(os.path.basename(line))[0]

    data = get_zip_data(download, zippath)

    exe = probe_for_exe(data)
    if not exe:
        print(f"No executable found in {zip32}, skipping")
        return False

    req = requests.head(download64, headers=HEADERS, timeout=60)
    pause_between_requests()
    x64 = bool(req.ok)
    if x64:
        print(f"Found 64-bit download: {download64}")
        data64 = get_zip_data(download64, zippath64)
    else:
        data64 = b""

    json_file = "bucket/" + name + ".json"
    existing = {}
    if os.path.isfile(json_file):
        print(f"Reading {json_file}")
        with open(json_file, "r", encoding="utf-8") as j:
            existing = json.load(j)

    hash_ = existing.get("hash", "tbd")
    architecture = existing.get("architecture", {})
    bit32 = architecture.get("32bit", {})
    bit64 = architecture.get("64bit", {})
    hash32 = bit32.get("hash", "tbd")
    hash64 = bit64.get("hash", "tbd")

    rehash = version != existing.get("version", "n/a")
    if not x64:
        if rehash or hash_ == "tbd":
            hash_ = sha256sum(data)
    else:
        if rehash or hash32 == "tbd":
            hash32 = sha256sum(data)
        if rehash or hash64 == "tbd":
            hash64 = sha256sum(data64)

    shortcut = "NirSoft\\" + full_name

    manifest = {
        "version": version,
        "homepage": website,
        "url": download,
        "bin": exe,
        "shortcuts": [[exe, shortcut]],
        "persist": [name + "_lng.ini", name + ".cfg"],
        "hash": hash_,
        "architecture": "",
        "description": description,
        "license": "Freeware",
        "notes": NOTES,
        "checkver": {
            "url": "https://www.nirsoft.net/pad/" + name + ".xml",
            "xpath": "/XML_DIZ_INFO/Program_Info/Program_Version",
        },
        "autoupdate": {"url": download},
    }

    if x64:
        manifest.pop("url")
        manifest.pop("hash")
        manifest["autoupdate"] = {
            "architecture": {"64bit": {"url": download64}, "32bit": {"url": download}},
        }
        manifest["architecture"] = {
            "64bit": {"url": download64, "hash": hash64},
            "32bit": {"url": download, "hash": hash32},
        }
    else:
        manifest.pop("architecture")
        manifest["url"] = download
        manifest["hash"] = hash_

    rewrite_json(json_file, manifest)

    return True


def rewrite_json(json_file: str, manifest: dict[str, T.Any]) -> bool:
    """rewrite_json"""
    if os.path.isfile(json_file):
        with open(json_file, "r", encoding="utf-8") as j:
            old = json.dumps(json.load(j))
            new = json.dumps(manifest)
            old = re.sub(r"\s+", " ", old)  # ignore whitespace differences
            new = re.sub(r"\s+", " ", new)
            # don't rewrite the file if nothing changed
            if old == new:
                print(f"Skipping writing {json_file}: no changes")
                return True

    print(f"Writing {json_file}")
    with open(json_file, "w", encoding="utf-8", newline="\n") as j:
        json.dump(manifest, j, indent=4)
    return True


if __name__ == "__main__":
    sys.exit(main())

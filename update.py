#!/usr/bin/env python3
"""update.py"""
# pylint: disable=C0103 # Constant name "description" doesn't conform to UPPER_CASE naming style (invalid-name)
# pylint: disable=W0703 # Catching too general exception Exception (broad-except)

import codecs
import csv
import hashlib
import io
import json
import os
import re
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
CACHE_DOWNLOADS = os.environ.get("CACHE_DOWNLOADS", False)
NOTES = "If this application is useful to you, please consider donating to NirSoft - https://www.nirsoft.net/donate.html"
PADLINKS_URL = "https://www.nirsoft.net/pad/pad-links.txt"
REFERER = "https://www.nirsoft.net/"
# 10 seconds per request could cause each run to take about 2h 45m, but if we get caching working, it should only take <50m on average.
SECONDS_BETWEEN_REQUESTS = 10
SI_HEADERS: dict[str, str] = {"Referer": "https://github.com/ScoopInstaller/Nirsoft"}
URLS_CSV = os.path.join(CACHE_DIR, "urls.csv")
URLS_FIELDS: list[str] = ["url", "status", "last_modified", "hash", "exe"]

HEADERS = {"Referer": REFERER}

UrlEntry = dict[str, T.Any]
Urls = dict[str, UrlEntry]


def pause_between_requests() -> None:
    """pause_between_requests"""
    if os.environ.get("CI", "") == "true":
        time.sleep(SECONDS_BETWEEN_REQUESTS)


def get_mtime(req: T.Any) -> float:
    """get_mtime"""
    url_time = req.headers["last-modified"]
    url_dt = parsedate(url_time)
    return url_dt.timestamp()


def get(url: str) -> bytes:
    """get"""
    cached_zip = os.path.join(CACHE_DIR, os.path.basename(url))
    if CACHE_DOWNLOADS and os.path.isfile(cached_zip):
        print(f"Reading {cached_zip}")
        with io.open(cached_zip, "rb") as fh:
            return fh.read()

    print(f"Downloading {url}...")
    req = requests.get(url, headers=HEADERS, timeout=60)
    pause_between_requests()
    req.raise_for_status()

    if CACHE_DOWNLOADS:
        print(f"Writing {cached_zip}")
        with io.open(cached_zip, "wb") as fh:
            fh.write(req.content)
        mtime = get_mtime(req)
        # print(f"Setting time of {cached_zip} to {mtime}")
        os.utime(cached_zip, (mtime, mtime))

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


def update_row(row: UrlEntry, url: str, report_404s: bool = True) -> tuple[bool, UrlEntry]:
    """update_row"""

    req = requests.head(url, headers=HEADERS, timeout=60)
    pause_between_requests()
    row["url"] = url
    row["status"] = req.status_code
    if not bool(req.ok):
        if req.status_code != 404 or report_404s:
            print(f"Cannot download {url}: {req.status_code}: {req.reason}")
        return (False, row)

    mtime = get_mtime(req)

    if not row["last_modified"]:
        row["last_modified"] = "0"
    if mtime > float(row["last_modified"]):
        row["last_modified"] = str(mtime)
        data = get(url)
        row["hash"] = sha256sum(data)
        row["exe"] = probe_for_exe(data)
    else:
        cached_zip = os.path.join(CACHE_DIR, os.path.basename(url))
        if CACHE_DOWNLOADS and os.path.isfile(cached_zip):
            # print(f"Setting time of {cached_zip} to {mtime}")
            os.utime(cached_zip, (mtime, mtime))

    return (True, row)


def main() -> int:
    """main"""
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    urls: Urls = {}

    if os.path.isfile(URLS_CSV):
        with io.open(URLS_CSV, "r", encoding="utf8", newline="") as fh:
            reader = csv.DictReader(fh, lineterminator="\n")
            for row in reader:
                urls[row["url"]] = row

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
            urls = do_padfile(line, urls)
        except Exception:
            print_exc()

    print(f"Processed {pad_lines} manifests")

    with io.open(URLS_CSV, "a", encoding="utf8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=URLS_FIELDS, lineterminator="\n")
        writer.writeheader()
        for _, row in urls.items():
            writer.writerow(row)

    return 0


# @TODO(rasa) rewrite this to use a dataclass
# pylint: disable=R0912 # Too many branches (17/12) (too-many-branches)
# pylint: disable=R0914 # Too many local variables (34/15) (too-many-locals)
# pylint: disable=R0915 # Too many statements (88/50) (too-many-statements)
def do_padfile(line: str, urls: Urls) -> Urls:
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
    row: UrlEntry = urls.get(download, dict.fromkeys(URLS_FIELDS, ""))
    (rv, row) = update_row(row, download)
    if download not in urls:
        urls[download] = row
    if not rv:
        # don't update urls on temporary 404s
        return urls

    urls[download] = row

    if not row["exe"]:
        print(f"No executable found in {download}, skipping")
        return urls

    download64 = download.replace(".zip", "-x64.zip")
    row64: UrlEntry = urls.get(download64, dict.fromkeys(URLS_FIELDS, ""))
    (x64, row64) = update_row(row64, download64, False)
    if download64 not in urls:
        urls[download64] = row64

    name = os.path.splitext(os.path.basename(line))[0]
    json_file = "bucket/" + name + ".json"

    if os.path.isfile(json_file):
        print(f"Reading {json_file}")
        with open(json_file, "r", encoding="utf-8") as j:
            manifest = json.load(j)
            architecture = manifest.get("architecture", {})
            bit64 = architecture.get("64bit", {})
            url64 = bit64.get("url", "")
            if not x64 and url64:
                # don't update urls on temporary 404s
                print(f"{json_file} has {url64} but cannot access {download64}, skipping")
                return urls

    urls[download64] = row64

    shortcut = "NirSoft\\" + full_name
    exe = row["exe"]
    hash32 = row["hash"]
    manifest = {
        "version": version,
        "homepage": website,
        "url": download,
        "bin": exe,
        "shortcuts": [[exe, shortcut]],
        "persist": [name + "_lng.ini", name + ".cfg"],
        "hash": hash32,
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
        hash64 = row64["hash"]
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
        manifest["hash"] = hash32

    rewrite_json(json_file, manifest)

    return urls


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

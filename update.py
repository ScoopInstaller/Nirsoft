#!/usr/bin/env python3
"""update.py"""
# pylint: disable=C0103 # Constant name "description" doesn't conform to UPPER_CASE naming style (invalid-name)
# pylint: disable=W0703 # Catching too general exception Exception (broad-except)

import codecs
import csv
import datetime as DT
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
PADS_ZIP_URL = "https://www.nirsoft.net/pad/pads.zip"
REFERER = "https://www.nirsoft.net/"
# 10 seconds per request could cause each run to take 3 hours or more, but with caching it should only take <50m on average.
SECONDS_BETWEEN_REQUESTS = 10
SI_HEADERS: dict[str, str] = {"Referer": "https://github.com/ScoopInstaller/Nirsoft"}
URLS_CSV = os.path.join(CACHE_DIR, "urls.csv")
URLS_FIELDS: list[str] = ["url", "status", "last_modified", "hash", "exe"]

HEADERS = {"Referer": REFERER}

PASSWORDS: dict[str, str] = {
    'chromepass': 'chpass9126*',
    'dialupass': 'nsdlps3861@',
    'iepv': 'iepv68861$',
    'netpass': 'ntps5291#',
    'passwordfox': 'nspsfx403!',
    'webbrowserpassview': 'wbpv28821@',
    'wirelesskeyview': 'WKey4567#',
}

UrlEntry = dict[str, T.Any]
Urls = dict[str, UrlEntry]


def check_404s() -> bool:
    """check_404s"""
    if len(sys.argv) > 2 and len(sys.argv[2]) > 0:
        return bool(sys.argv[2])
    return bool(os.environ.get("CHECK_404S", False))


def seconds_to_sleep() -> int:
    """seconds_to_sleep"""
    if len(sys.argv) > 1 and len(sys.argv[1]) > 0:
        return int(sys.argv[1])
    if not os.environ.get("CI", False):
        return 0
    return SECONDS_BETWEEN_REQUESTS


def pause_between_requests() -> None:
    """pause_between_requests"""
    time.sleep(seconds_to_sleep())


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
        print(f"{exc}: expected a .zips' 504b magic signature, found {encoded!r}:")
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

    if row["status"] and int(row["status"]) == 404 and not check_404s():
        return (False, row)

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

    cached_zip = os.path.join(CACHE_DIR, os.path.basename(url))
    if CACHE_DOWNLOADS and os.path.isfile(cached_zip):
        try:
            # print(f"Setting time of {cached_zip} to {mtime}")
            os.utime(cached_zip, (mtime, mtime))
        except Exception:
            pass  # ignore failures

    return (True, row)


# pylint: disable=R0914 # Too many local variables (17/15) (too-many-locals)
def main() -> int:
    """main"""
    print(f"Sleeping {seconds_to_sleep()} seconds between requests")

    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    urls: Urls = {}

    if os.path.isfile(URLS_CSV):
        with io.open(URLS_CSV, "r", encoding="utf8", newline="") as fh:
            reader = csv.DictReader(fh, lineterminator="\n")
            for row in reader:
                urls[row["url"]] = row

    print(f"Fetching {PADS_ZIP_URL}")
    req = requests.get(PADS_ZIP_URL, headers=SI_HEADERS, timeout=60)
    pause_between_requests()
    req.raise_for_status()
    
    start = time.time()
    done = 0
    with zipfile.ZipFile(BytesIO(req.content)) as z:
        total_pads = len(z.namelist())
        for pad_name in z.namelist(): 
            with z.open(pad_name) as zh:
                pad_data = str(zh.read(), "utf-8")
                done += 1
                index = done - 1
                elapsed_each = (time.time() - start) / index if index else 0.0
                remaining_seconds = (total_pads - index) * elapsed_each
                remaining_time = str(DT.timedelta(seconds=remaining_seconds))
                # strip off fractional seconds:
                remaining_time = re.sub(r"\.\d+\s*$", "", remaining_time)
                completed_pct = 100.0 * index / total_pads
                print(f"{done:3d}/{total_pads}: {completed_pct:5.2f}% complete, {remaining_time} left, processing {pad_name}")
                try:
                    urls = do_padfile(pad_name, pad_data, urls)
                except Exception:
                    print_exc()

    print(f"Processed {total_pads} manifests")

    with io.open(URLS_CSV, "w", encoding="utf8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=URLS_FIELDS, lineterminator="\n")
        writer.writeheader()
        for _, row in urls.items():
            writer.writerow(row)

    return 0


# @TODO(rasa) rewrite this to use a dataclass
# pylint: disable=R0912 # Too many branches (17/12) (too-many-branches)
# pylint: disable=R0914 # Too many local variables (34/15) (too-many-locals)
# pylint: disable=R0915 # Too many statements (88/50) (too-many-statements)
def do_padfile(pad_name: str, pad_data: str, urls: Urls) -> Urls:
    """do_padfile"""

    version = ""
    full_name = ""
    website = ""
    download = ""
    description = ""

    root = ET.fromstring(pad_data)

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

    name = os.path.splitext(os.path.basename(pad_name))[0]
    json_file = "bucket/" + name + ".json"

    if os.path.isfile(json_file):
        # print(f"Reading {json_file}")
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

    manifest["pre_install"] = [
        r'if (-not (Test-Path \"$persist_dir\\'+ name + r'.cfg\")) { New-Item \"$dir\\' +name + r'.cfg\" -ItemType file | Out-Null }',
        r'if (-not (Test-Path \"$persist_dir\\' + name + r'_lng.ini\")) { New-Item \"$dir\\' + name + r'_lng.ini\" -ItemType file | Out-Null }',
    ]
    # See https://github.com/ScoopInstaller/Nirsoft/issues/17
    # See https://github.com/ScoopInstaller/Nirsoft/issues/46
    password = PASSWORDS.get(name, '')
    if password:
        arch = manifest.get("architecture", '')
        if arch:
            if arch.get("64bit", ''):
                manifest["architecture"]["64bit"]["url"] += "#dl.zip_"
            if arch.get("32bit", ''):
                manifest["architecture"]["32bit"]["url"] += "#dl.zip_"
        else:
            manifest["url"] += "#dl.zip_"
        manifest["pre_install"].append(r"$zip=(Get-ChildItem $dir\\" + name + "*).Name")
        manifest["pre_install"].append(r"7z x $dir\\$zip -p'" + password + "' $('-o' + $dir) | Out-Null")

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
                # print(f"Skipping writing {json_file}: no changes")
                return True

    print(f"Writing {json_file}")
    with open(json_file, "w", encoding="utf-8", newline="\n") as j:
        json.dump(manifest, j, indent=4)
    return True


if __name__ == "__main__":
    sys.exit(main())

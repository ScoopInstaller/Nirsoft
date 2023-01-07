"""update.py"""
# pylint: disable=C0103 # Constant name "description" doesn't conform to UPPER_CASE naming style (invalid-name)
# pylint: disable=W0703 # Catching too general exception Exception (broad-except)

import json
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from traceback import print_exc
from zipfile import ZipFile

import requests

HEADERS = {"Referer": "https://github.com/ScoopInstaller/Nirsoft"}


def probe_for_exe(url):
    """probe_for_exe"""
    print("Downloading " + url + "...")
    req = requests.get(url, headers=HEADERS, timeout=60)
    req.raise_for_status()
    with ZipFile(BytesIO(req.content)) as z:
        for filename in z.namelist():
            if filename.endswith(".exe"):
                return filename
    return ""


if __name__ == "__main__":
    print("Fetching Padfile links")
    pads = requests.get("https://www.nirsoft.net/pad/pad-links.txt", timeout=60).text

    i = 0
    for line in pads.splitlines():
        i += 1
        print("")
        print("Generating from " + line + " (" + str(i) + "/" + str(len(pads.splitlines())) + ")")

        version = ""
        full_name = ""
        website = ""
        download = ""
        description = ""

        try:
            padfile = requests.get(line, timeout=60).text
            root = ET.fromstring(padfile)

            try:
                info = root.find("Program_Info")
            except Exception:
                pass
            try:
                version = info.find("Program_Version").text  # type: ignore
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

            download = download.replace("http:", "https:")

            download64 = download.replace(".zip", "-x64.zip")
            name = os.path.splitext(os.path.basename(line))[0]

            exe = probe_for_exe(download)
            if not exe:
                print("No executable found! Skipping")
                continue

            shortcut = "NirSoft\\" + full_name
            try:
                descriptions = root.find("Program_Descriptions").find("English")  # type: ignore
                description = descriptions.find("Char_Desc_80").text  # type: ignore
            except AttributeError:
                description = ""

            print("Checking 64-bit download url")
            r = requests.head(download64, headers=HEADERS, timeout=60)
            x64 = bool(r.ok)
            if not x64:
                print("64-bit download unavailable")

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
                "notes": "If this application is useful to you, please consider donating to nirsoft.",
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
                manifest["architecture"] = {"64bit": {"url": download64, "hash": hash64}, "32bit": {"url": download, "hash": hash32}}
            else:
                manifest.pop("architecture")
                manifest["url"] = download
                manifest["hash"] = hash32

            print(f"Writing {json_file}")
            with open(json_file, "w", encoding="utf-8", newline="\n") as j:
                json.dump(manifest, j, indent=1)

        except Exception:
            print_exc()

    print("")
    # handled now by GitHub action:
    # print("Running checkver -f")
    # subprocess.run(["powershell", "-Command", r".\bin\checkver.ps1", "-f"])

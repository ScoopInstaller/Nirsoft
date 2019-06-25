import os
import json
import xml.etree.ElementTree as ET
import requests
from zipfile import ZipFile
from io import BytesIO
import time

def probe_for_exe(url):
    print("Downloading " + download + "...")
    r = requests.get(download)
    with ZipFile(BytesIO(r.content)) as z:
        for name in z.namelist():
            if name.endswith(".exe"):
                return name

pads = requests.get("https://www.nirsoft.net/pad/pad-links.txt").text

i = 0
for line in pads.splitlines():
    i += 1
    if i % 5 == 0:
        print("Sleeping 5 seconds to not spam the server")
        time.sleep(5)
    print("")
    print("Generating from " + line + " (" + str(i) + "/" + str(len(pads.splitlines())) + ")")

    try:
        padfile = requests.get(line).text
        root = ET.fromstring(padfile)

        info = root.find("Program_Info")
        version = info.find("Program_Version").text
        full_name = info.find("Program_Name").text

        web_info = root.find("Web_Info")
        website = web_info.find("Application_URLs").find("Application_Info_URL").text.replace("http:", "https:")
        download = web_info.find("Download_URLs").find("Primary_Download_URL").text.replace("http:", "https:")
        download64 = download.replace(".zip", "-x64.zip")
        name = os.path.splitext(os.path.basename(line))[0]

        bin = probe_for_exe(download)
        if not bin:
            print("No executable found! Skipping")

        description = ""
        shortcut = "NirSoft\\" + full_name
        try:
            descriptions = root.find("Program_Descriptions").find("English")
            description = descriptions.find("Char_Desc_80").text
            # shortcut += " - " + descriptions.find("Char_Desc_45").text # Disabled for now, see lukesampson/scoop#3526
        except AttributeError:
            pass

        print("Checking 64-bit download url")
        r = requests.head(download64)
        x64 = bool(r.ok)
        if not x64:
            print("64-bit download unavailable")


        manifest = {
            "version": "0",
            "homepage": website,
            "url": download,
            "bin": bin,
            "shortcuts": [
                [ bin, shortcut ]
            ],
            "hash": "tbd",
            "architecture": "",
            "description": description,
            "license": "Freeware",
            "notes": "If this application is useful to you, please consider donating to nirsoft.",
            "checkver": {
                "url": "https://www.nirsoft.net/pad/" + name + ".xml",
                "xpath": "/XML_DIZ_INFO/Program_Info/Program_Version"
            },
            "autoupdate": {
                "url": download
            }
        }

        if x64:
            manifest.pop("url")
            manifest.pop("hash")
            manifest["autoupdate"] = {
                "architecture": {
                    "64bit": {
                        "url": download64
                    },
                    "32bit": {
                        "url": download
                    }
                },
            }
            manifest["architecture"] = {
                "64bit": {
                "url": download64,
                "hash": "tbd"
                },
                "32bit": {
                    "url": download,
                    "hash": "tbd"
                }
            }
        else:
            manifest.pop("architecture")
            manifest["url"] = download
            manifest["hash"] = "tbd"

        with open("bucket/" + name + ".json", "w") as j:
            json.dump(manifest, j, indent=1)

    except Exception as e:
        print("Exception! " + str(e))

import os
import time
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

DOWNLOAD_DIR = os.getenv("BMF_DOWNLOAD_DIR", "data/raw/bmf")
POSTING_DATE = os.getenv("BMF_POSTING_DATE", "").strip()
DISCOVERY_FILE = os.path.join(DOWNLOAD_DIR, "bmf_discovery.txt")

STATES_RAW = os.getenv("BMF_DOWNLOAD_STATES", "wa").strip().lower()
TIMEOUT = int(os.getenv("BMF_DOWNLOAD_TIMEOUT", "120"))


def read_discovery_links(path: str) -> list[str]:
    links = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("http"):
                links.append(line)
    return links


def state_code_from_url(url: str) -> str | None:
    name = os.path.basename(urlparse(url).path).lower()
    if name.startswith("eo_") and name.endswith(".csv"):
        return name[3:5]
    return None


def download_file(url: str, out_path: str, timeout: int = 120, retries: int = 3) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        print("SKIP (exists):", out_path)
        return

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            print(f"Downloading (attempt {attempt}): {url}")
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                tmp_path = out_path + ".part"
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp_path, out_path)
            print("OK:", out_path)
            return
        except Exception as e:
            last_err = e
            print("Retry error:", e)
            time.sleep(2 * attempt)

    raise RuntimeError(f"Failed to download after {retries} attempts: {url}\nLast error: {last_err}")


def main():
    if not POSTING_DATE:
        raise ValueError("BMF_POSTING_DATE missing in .env")

    if not os.path.exists(DISCOVERY_FILE):
        raise FileNotFoundError(f"Discovery file not found: {DISCOVERY_FILE}")

    links = read_discovery_links(DISCOVERY_FILE)

    out_folder = os.path.join(DOWNLOAD_DIR, POSTING_DATE)
    os.makedirs(out_folder, exist_ok=True)

    if STATES_RAW == "all":
        # Fix: filter out non-BMF URLs (e.g. SOI files, SIT files)
        # Only include URLs that match the eo_<state>.csv pattern
        selected = [(st, url) for url in links if (st := state_code_from_url(url))]
        print(f"Downloading ALL states — {len(selected)} valid BMF files found")
    else:
        states = [s.strip() for s in STATES_RAW.split(",") if s.strip()]
        selected = []
        for url in links:
            st = state_code_from_url(url)
            if st and st in states:
                selected.append((st, url))
        print("States requested:", states)

    if not selected:
        raise RuntimeError("No matching state links found.")

    print("Files to download:", len(selected))

    for st, url in selected:
        filename = os.path.basename(urlparse(url).path)
        out_path = os.path.join(out_folder, filename)
        download_file(url, out_path, timeout=TIMEOUT, retries=3)

    print("Download complete.")


if __name__ == "__main__":
    main()

import os
import subprocess
import sys

def run(cmd: list[str]) -> None:
    print("\nRUN:", " ".join(cmd))
    p = subprocess.run(cmd, capture_output=False)
    if p.returncode != 0:
        raise SystemExit(p.returncode)

def main():
    # Run in order
    run([sys.executable, "src/bmf/step3_discover_bmf_links.py"])
    run([sys.executable, "src/bmf/step4_download_bmf_csvs.py"])
    run([sys.executable, "src/bmf/step6_parse_load_with_runlog.py"])

if __name__ == "__main__":
    main()
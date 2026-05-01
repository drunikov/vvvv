#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from xml.sax.saxutils import escape

def ensure_easytello_installed():
    try:
        from easytello import tello as _tello
        return _tello
    except ImportError:
        if getattr(sys, "frozen", False):
            raise RuntimeError("easytello module missing in packaged build")
        print("easytello not found. Installing automatically...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "easytello"])
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("Failed to auto-install easytello. Install manually with: pip install easytello") from exc

        try:
            from easytello import tello as _tello
            return _tello
        except ImportError as exc:
            raise RuntimeError("easytello installation completed but import still failed") from exc


tello = ensure_easytello_installed()


def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Command failed")
    return result.stdout.strip()


def nmcli_available():
    return shutil.which("nmcli") is not None


def netsh_available():
    return shutil.which("netsh") is not None


def connected_ssid_linux():
    output = run_cmd(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
    for line in output.splitlines():
        if line.startswith("yes:"):
            return line.split(":", 1)[1]
    return ""


def scan_tello_ssids_linux():
    output = run_cmd(["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list", "--rescan", "yes"])
    ssids = []
    for line in output.splitlines():
        ssid = line.strip()
        if ssid and ssid.startswith("TELLO-") and ssid not in ssids:
            ssids.append(ssid)
    return ssids


def connected_ssid_windows():
    output = run_cmd(["netsh", "wlan", "show", "interfaces"])
    for line in output.splitlines():
        match = re.match(r"^\s*SSID\s*:\s*(.+)$", line)
        if match and "BSSID" not in line:
            value = match.group(1).strip()
            if value and value.lower() != "n/a":
                return value
    return ""


def scan_tello_ssids_windows():
    output = run_cmd(["netsh", "wlan", "show", "networks", "mode=Bssid"])
    ssids = []
    for line in output.splitlines():
        match = re.match(r"^\s*SSID\s+\d+\s*:\s*(.*)$", line)
        if match:
            ssid = match.group(1).strip()
            if ssid.startswith("TELLO-") and ssid not in ssids:
                ssids.append(ssid)
    return ssids


def add_windows_open_profile(ssid):
    safe_ssid = escape(ssid)
    profile_xml = f"""<?xml version=\"1.0\"?>
<WLANProfile xmlns=\"http://www.microsoft.com/networking/WLAN/profile/v1\">
    <name>{safe_ssid}</name>
    <SSIDConfig>
        <SSID>
            <name>{safe_ssid}</name>
        </SSID>
    </SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>manual</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>open</authentication>
                <encryption>none</encryption>
                <useOneX>false</useOneX>
            </authEncryption>
        </security>
    </MSM>
</WLANProfile>
"""

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as tmp:
            tmp.write(profile_xml)
            temp_path = tmp.name
        run_cmd(["netsh", "wlan", "add", "profile", f"filename={temp_path}", "user=current"])
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def connect_to_wifi_linux(target_ssid=None, timeout=20):
    if not nmcli_available():
        raise RuntimeError("nmcli not found. Install NetworkManager or connect to drone Wi-Fi manually.")

    current = connected_ssid_linux()
    if target_ssid and current == target_ssid:
        print(f"Already connected to {target_ssid}")
        return target_ssid
    if not target_ssid and current.startswith("TELLO-"):
        print(f"Already connected to {current}")
        return current

    ssid = target_ssid
    if not ssid:
        candidates = scan_tello_ssids_linux()
        if not candidates:
            raise RuntimeError("No TELLO-* Wi-Fi network found. Turn on the drone and try again.")
        ssid = candidates[0]

    print(f"Connecting to Wi-Fi: {ssid}")
    run_cmd(["nmcli", "dev", "wifi", "connect", ssid])

    start = time.time()
    while time.time() - start < timeout:
        if connected_ssid_linux() == ssid:
            print(f"Connected to {ssid}")
            return ssid
        time.sleep(1)

    raise RuntimeError(f"Timed out while connecting to {ssid}")


def connect_to_wifi_windows(target_ssid=None, timeout=20):
    if not netsh_available():
        raise RuntimeError("netsh not found. Connect to drone Wi-Fi manually.")

    current = connected_ssid_windows()
    if target_ssid and current == target_ssid:
        print(f"Already connected to {target_ssid}")
        return target_ssid
    if not target_ssid and current.startswith("TELLO-"):
        print(f"Already connected to {current}")
        return current

    ssid = target_ssid
    if not ssid:
        candidates = scan_tello_ssids_windows()
        if not candidates:
            raise RuntimeError("No TELLO-* Wi-Fi network found. Turn on the drone and try again.")
        ssid = candidates[0]

    print(f"Connecting to Wi-Fi: {ssid}")
    add_windows_open_profile(ssid)
    run_cmd(["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"])

    start = time.time()
    while time.time() - start < timeout:
        if connected_ssid_windows() == ssid:
            print(f"Connected to {ssid}")
            return ssid
        time.sleep(1)

    raise RuntimeError(f"Timed out while connecting to {ssid}")


def connect_to_wifi(target_ssid=None, timeout=20):
    if sys.platform.startswith("win"):
        return connect_to_wifi_windows(target_ssid=target_ssid, timeout=timeout)
    return connect_to_wifi_linux(target_ssid=target_ssid, timeout=timeout)


def fly_square(drone, side_cm=200, edge_pause=1.0):
    if side_cm < 20 or side_cm > 500:
        raise ValueError("side_cm must be between 20 and 500 cm for Tello command limits")

    print("Takeoff")
    drone.takeoff()
    time.sleep(2)

    for i in range(4):
        print(f"Edge {i + 1}/4: forward {side_cm} cm")
        drone.forward(side_cm)
        time.sleep(edge_pause)

        print("Rotate clockwise 90°")
        drone.cw(90)
        time.sleep(edge_pause)

    print("Landing")
    drone.land()


def main():
    parser = argparse.ArgumentParser(
        description="Auto-connect to Tello Wi-Fi and fly a 200x200 cm square mission (Linux/Windows)"
    )
    parser.add_argument(
        "--ssid",
        default=None,
        help="Specific Tello SSID to connect (example: TELLO-AB12CD)",
    )
    parser.add_argument(
        "--side-cm",
        type=int,
        default=200,
        help="Square side length in cm (20-500). Default: 200",
    )
    args = parser.parse_args()

    try:
        connect_to_wifi(args.ssid)

        print("Connecting to drone command interface...")
        drone = tello.Tello()
        time.sleep(1)

        fly_square(drone, side_cm=args.side_cm)
        print("Mission complete")

    except KeyboardInterrupt:
        print("Interrupted by user")
        sys.exit(130)
    except Exception as exc:
        print(f"Mission failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

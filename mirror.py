"""Builds servers.csv for the ShieldVPN app from several free OpenVPN sources.

Output uses VPN Gate's CSV format (so the app has one parser) and keeps every
server seen in the last 48 hours, newest first. Each source is optional: if one
is down or blocked, the others still update.
"""
import base64
import json
import os
import re
import socket
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
HEADER = ("#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,NumVpnSessions,Uptime,"
          "TotalUsers,TotalTraffic,LogType,Operator,Message,OpenVPN_ConfigData_Base64")
KEEP_SECONDS = 48 * 3600


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def row(host, ip, score, country_long, country_short, operator, config):
    b64 = base64.b64encode(config.encode()).decode()
    fields = [host, ip, str(score), "0", "0", country_long, country_short, "0", "0", "0", "0",
              "unknown", operator, "", b64]
    return ",".join(f.replace(",", " ") for f in fields)


def vpngate():
    body = get("http://www.vpngate.net/api/iphone/")
    if not body.lstrip().startswith("*vpn_servers"):
        raise RuntimeError("not a server list")
    return [r.strip() for r in body.splitlines()
            if r.strip() and r.strip()[0] not in "*#" and r.count(",") >= 14]


VPNBOOK_COUNTRIES = {"us": ("United States", "US"), "ca": ("Canada", "CA"), "uk": ("United Kingdom", "GB"),
                     "de": ("Germany", "DE"), "fr": ("France", "FR"), "pl": ("Poland", "PL")}


def vpnbook():
    page = get("https://www.vpnbook.com/freevpn")
    m = re.search(r"Username:\s*(\w+)\.\s*Password:\s*(\w+)", page)
    if not m:
        raise RuntimeError("password not found")
    user, password = m.groups()
    hosts = sorted(set(re.findall(r"\b([a-z]{2}\d+)\.vpnbook\.com", page)))
    rows = []
    for h in hosts:
        prefix = h[:2]
        if prefix not in VPNBOOK_COUNTRIES:
            continue
        fqdn = f"{h}.vpnbook.com"
        try:
            cfg = get(f"https://www.vpnbook.com/api/openvpn?hostname={fqdn}&protocol=tcp443", timeout=30)
            if "<ca>" not in cfg:
                continue
            ip = socket.gethostbyname(fqdn)
        except Exception as e:  # one dead server shouldn't stop the rest
            print(f"vpnbook {fqdn}: {e}")
            continue
        cfg = re.sub(r"(?m)^auth-user-pass[ \t]*\n?", "", cfg.replace("\r", ""))
        cfg += f"\n<auth-user-pass>\n{user}\n{password}\n</auth-user-pass>\n"
        name, code = VPNBOOK_COUNTRIES[prefix]
        rows.append(row(f"vpnbook-{h}", ip, 500000, name, code, "VPNBook", cfg))
    return rows


def main():
    now = int(time.time())
    seen = json.load(open("seen.json")) if os.path.exists("seen.json") else {}
    for name, source in [("VPN Gate", vpngate), ("VPNBook", vpnbook)]:
        try:
            rows = source()
        except Exception as e:
            print(f"{name}: failed ({e}); keeping previous rows")
            continue
        for r in rows:
            seen[",".join(r.split(",", 2)[:2])] = [now, r]
        print(f"{name}: {len(rows)} servers")
    seen = {k: v for k, v in seen.items() if now - v[0] < KEEP_SECONDS}
    rows = sorted(seen.values(), key=lambda v: -v[0])[:2000]
    with open("servers.csv", "w", encoding="utf-8", newline="\n") as f:
        f.write("*vpn_servers\n" + HEADER + "\n" + "\n".join(r for _, r in rows) + "\n*\n")
    with open("seen.json", "w") as f:
        json.dump(seen, f)
    print(f"total: {len(rows)} servers, {len({r.split(',')[6] for _, r in rows})} countries")


if __name__ == "__main__":
    main()

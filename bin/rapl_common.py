"""Shared collection logic for TA-rapl (powercap RAPL + hwmon power sensors)."""
import json
import os
import re
import subprocess
import sys

POWERCAP = "/sys/class/powercap"
HWMON = "/sys/class/hwmon"
RAPL_PREFIX = "intel-rapl"
RAPL_CAT = "/usr/local/sbin/ta_rapl_cat"


def read_file(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def sudo_read(path):
    """Read a sysfs file via the ta_rapl_cat sudo wrapper (energy_uj is 0400 root)."""
    if not os.path.exists(RAPL_CAT):
        return None
    lines = run_lines(["/usr/bin/sudo", "-n", RAPL_CAT, path], timeout=10)
    if not lines:
        return None
    return lines[0].strip() or None


def read_powercap_attr(path, fn):
    full = os.path.join(path, fn)
    val = read_file(full)
    if val is None:
        val = sudo_read(full)
    return val


def run_lines(cmd, timeout=25):
    """Run a command, return stdout lines or None on any failure."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    return p.stdout.splitlines()


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _sanitize(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "unknown"


def _domain_key(dirname):
    suffix = dirname[len(RAPL_PREFIX):] if dirname.startswith(RAPL_PREFIX) else dirname
    return _sanitize(suffix) or "0"


def _read_powercap_dir(path, entry):
    # A directory is a RAPL domain iff an energy_uj attribute exists; unreadable
    # (EACCES) must not be mistaken for absent, else powercap vanishes fleet-wide.
    if not os.path.exists(os.path.join(path, "energy_uj")):
        return None
    energy = _int(read_powercap_attr(path, "energy_uj"))
    rec = {
        "name": _sanitize(read_powercap_attr(path, "name") or entry),
        "energy_readable": 1 if energy is not None else 0,
    }
    if energy is not None:
        rec["energy_uj"] = energy
    mx = _int(read_powercap_attr(path, "max_energy_range_uj"))
    if mx is not None:
        rec["max_energy_range_uj"] = mx
    limits = []
    try:
        files = os.listdir(path)
    except OSError:
        files = []
    for fn in files:
        if re.match(r"^constraint_\d+_power_limit_uw$", fn):
            v = _int(read_powercap_attr(path, fn))
            if v is not None:
                limits.append(v)
    if limits:
        rec["max_power_limit_uw"] = max(limits)
        rec["min_power_limit_uw"] = min(limits)
    return rec


def _read_hwmon_chip(path, entry):
    name = _sanitize(read_file(os.path.join(path, "name")) or entry)
    rec = {}
    try:
        files = os.listdir(path)
    except OSError:
        return name, rec
    for fn in files:
        m = re.match(r"^power(\d+)_input$", fn)
        if not m:
            continue
        uw = _int(read_file(os.path.join(path, fn)))
        if uw is None:
            continue
        rec["power%s_watts" % m.group(1)] = round(uw / 1000000.0, 4)
    return name, rec


def discover():
    powercap = {}
    try:
        entries = sorted(os.listdir(POWERCAP))
    except OSError:
        entries = []
    for entry in entries:
        if not entry.startswith(RAPL_PREFIX):
            continue
        path = os.path.join(POWERCAP, entry)
        if not os.path.isdir(path):
            continue
        rec = _read_powercap_dir(path, entry)
        if rec is None:
            continue
        key = base = _domain_key(entry)
        n = 2
        while key in powercap:
            key = "%s_%d" % (base, n)
            n += 1
        powercap[key] = rec

    chips = {}
    try:
        entries = sorted(os.listdir(HWMON))
    except OSError:
        entries = []
    for entry in entries:
        m = re.match(r"^hwmon(\d+)$", entry)
        if not m:
            continue
        path = os.path.join(HWMON, entry)
        if not os.path.isdir(path):
            continue
        name, rec = _read_hwmon_chip(path, entry)
        if not rec:
            continue
        key = name
        if key in chips:
            key = "%s_%s" % (name, m.group(1))
        n = 2
        while key in chips:
            key = "%s_%d" % (key, n)
            n += 1
        chips[key] = rec

    status = "ok" if (powercap or chips) else "absent"
    return {"status": status, "powercap": powercap, "power_chips": chips}


def metrics_payload(data):
    data = data or {}
    powercap = data.get("powercap") or {}
    chips = data.get("power_chips") or {}
    payload = {"powercap_count": len(powercap), "chip_count": len(chips)}
    for domain, rec in powercap.items():
        energy = rec.get("energy_uj")
        if energy is not None:
            payload["pc_%s_energy_uj" % domain] = int(energy)
        mrange = rec.get("max_energy_range_uj")
        if mrange is not None:
            payload["pc_%s_max_energy_range_uj" % domain] = int(mrange)
    for chip, rec in chips.items():
        for key, val in rec.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val is not None:
                payload["%s_%s" % (chip, key)] = float(val)
    return payload


def emit(payload):
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def fail(message):
    sys.stderr.write("TA-rapl collection error: %s\n" % message)
    return 1

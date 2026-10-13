#!/usr/bin/env python3
"""Assemble and verify the builder config with WXR-only/package overrides."""

import argparse
import re
import sys
from pathlib import Path

DEVICE = "CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_buffalo_wxr-5950ax12"
PACKAGE = re.compile(r"([A-Za-z0-9][A-Za-z0-9+_.-]*)(?:=(y|m))?")
ASSIGNMENT = re.compile(r"(CONFIG_[A-Za-z0-9+_.-]+)=(.+)")
UNSET = re.compile(r"# (CONFIG_[A-Za-z0-9+_.-]+) is not set")
# A platform and subtarget must precede _DEVICE_; PER_DEVICE_ROOTFS is not
# a device selection, nor are TARGET_DEVICE_PACKAGES_* string options.
DEVICE_SYMBOL = re.compile(
    r"CONFIG_TARGET_(?!DEVICE_PACKAGES_)(?:DEVICE_)?[A-Za-z0-9]+_[A-Za-z0-9_]+_DEVICE_.+"
)


def read_config(path):
    values = {}
    for line in path.read_text().splitlines():
        if match := ASSIGNMENT.fullmatch(line):
            values[match[1]] = match[2]
        elif match := UNSET.fullmatch(line):
            values[match[1]] = "n"
    return values


def read_packages(path):
    packages = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        entry = raw.split("#", 1)[0].strip()
        if not entry:
            continue
        match = PACKAGE.fullmatch(entry)
        if not match:
            raise ValueError(f"Invalid package on line {number}: {entry!r}")
        name, mode = match[1], match[2] or "y"
        if name in packages and packages[name] != mode:
            raise ValueError(f"Conflicting package modes on line {number}: {name}")
        packages[name] = mode
    if {"tcpdump", "tcpdump-mini"} <= packages.keys():
        raise ValueError("Choose only one of tcpdump and tcpdump-mini (including =m)")
    return packages


def read_extra_config(path):
    values = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or (line.startswith("#") and not UNSET.fullmatch(line)):
            continue
        match = ASSIGNMENT.fullmatch(line) or UNSET.fullmatch(line)
        if not match or ("=" in line and match[2] != "y"):
            raise ValueError(f"Invalid extra config on line {number}: {line!r}")
        symbol = match[1]
        value = "n" if line.startswith("#") else "y"
        if symbol in values and values[symbol] != value:
            raise ValueError(f"Conflicting extra config on line {number}: {symbol}")
        values[symbol] = value
    return values


def write_config(path, values):
    path.write_text("".join(
        f"# {symbol} is not set\n" if value == "n" else f"{symbol}={value}\n"
        for symbol, value in values.items()
    ))


def prepare(builder, packages_path, config, required, extra_config=None):
    values = {}
    for fragment in ("devices/common/config", "devices/ipq807x-1g/config"):
        values.update(read_config(builder / fragment))
    if values.get(DEVICE) != "y":
        raise ValueError(f"Builder ipq807x-1g config must include {DEVICE}=y")
    for symbol in values:
        if DEVICE_SYMBOL.fullmatch(symbol):
            values[symbol] = "n"
    values.update({
        DEVICE: "y",
        "CONFIG_TARGET_MULTI_PROFILE": "y",
        "CONFIG_TARGET_PER_DEVICE_ROOTFS": "y",
        "CONFIG_TARGET_ALL_PROFILES": "n",
        "CONFIG_ATH11K_MEM_PROFILE_1G": "y",
        "CONFIG_NSS_MEM_PROFILE_HIGH": "y",
        "CONFIG_TARGET_ROOTFS_INITRAMFS": "n",
        "CONFIG_USE_APK": "y",
    })
    packages = read_packages(packages_path)
    for name, mode in packages.items():
        symbol = f"CONFIG_PACKAGE_{name}"
        if symbol in values:
            print(f"Package override: {name}: builder={values[symbol]}, requested={mode}")
        values[symbol] = mode
    protected = {
        DEVICE: "y",
        "CONFIG_TARGET_MULTI_PROFILE": "y",
        "CONFIG_TARGET_PER_DEVICE_ROOTFS": "y",
        "CONFIG_TARGET_ALL_PROFILES": "n",
        "CONFIG_TARGET_ROOTFS_INITRAMFS": "n",
        "CONFIG_ATH11K_MEM_PROFILE_1G": "y",
        "CONFIG_NSS_MEM_PROFILE_HIGH": "y",
        "CONFIG_USE_APK": "y",
    }
    if extra_config is not None:
        for symbol, value in read_extra_config(extra_config).items():
            if symbol in protected and value != protected[symbol]:
                raise ValueError(f"Extra config cannot change protected setting: {symbol}")
            if DEVICE_SYMBOL.fullmatch(symbol) and symbol != DEVICE and value != "n":
                raise ValueError(f"Extra config cannot enable another device: {symbol}")
            if symbol.startswith("CONFIG_PACKAGE_"):
                raise ValueError(f"Use packages.txt for package settings: {symbol}")
            if "QCA_MCS" in symbol.upper() and value != "n":
                raise ValueError(f"Extra config cannot enable qca-mcs: {symbol}")
            values[symbol] = value
    # Both variants install /usr/bin/tcpdump. No tcpdump is set in the pinned
    # common config, but also handle a builder_ref that adds either variant.
    disabled = {"CONFIG_TARGET_ALL_PROFILES", "CONFIG_TARGET_ROOTFS_INITRAMFS"}
    if extra_config is not None:
        disabled.update(symbol for symbol, value in read_extra_config(extra_config).items() if value == "n")
    for selected, other in (("tcpdump-mini", "tcpdump"), ("tcpdump", "tcpdump-mini")):
        if selected in packages:
            symbol = f"CONFIG_PACKAGE_{other}"
            values[symbol] = "n"
            disabled.add(symbol)
    write_config(config, values)
    # Retain the builder's verification of all requested non-n values, after
    # applying our overrides. Also assert the image/variant exclusions.
    write_config(required, {
        symbol: value for symbol, value in values.items()
        if value != "n" or symbol in disabled
    })


def verify(config, required):
    actual = read_config(config)
    failures = []
    for symbol, value in read_config(required).items():
        resolved = actual.get(symbol, "n")
        if value == "m" and resolved == "y":
            # Another package or the builder config selects it, so it is in the
            # image and its APK is still built: the request is satisfied.
            print(f"Notice: {symbol}=m resolved to y (selected by a dependency or the builder)")
        elif resolved != value:
            failures.append(f"Required configuration missing: {symbol}={value} (resolved: {resolved})")
    for symbol, value in actual.items():
        if DEVICE_SYMBOL.fullmatch(symbol) and value in ("y", "m") and symbol != DEVICE:
            failures.append(f"Unexpected device enabled: {symbol}={value}")
    if actual.get(DEVICE) != "y":
        failures.append(f"Required device missing: {DEVICE}=y")
    if failures:
        raise ValueError("\n".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--required", required=True, type=Path)
    parser.add_argument("--builder", type=Path)
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--extra-config", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.builder is None or args.packages is None:
                parser.error("prepare requires --builder and --packages")
            prepare(args.builder, args.packages, args.config, args.required, args.extra_config)
        else:
            verify(args.config, args.required)
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

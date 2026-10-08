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


def write_config(path, values):
    path.write_text("".join(
        f"# {symbol} is not set\n" if value == "n" else f"{symbol}={value}\n"
        for symbol, value in values.items()
    ))


def prepare(builder, packages_path, config, required):
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
    # Both variants install /usr/bin/tcpdump. No tcpdump is set in the pinned
    # common config, but also handle a builder_ref that adds either variant.
    disabled = {"CONFIG_TARGET_ALL_PROFILES", "CONFIG_TARGET_ROOTFS_INITRAMFS"}
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
        if resolved != value:
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
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.builder is None or args.packages is None:
                parser.error("prepare requires --builder and --packages")
            prepare(args.builder, args.packages, args.config, args.required)
        else:
            verify(args.config, args.required)
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

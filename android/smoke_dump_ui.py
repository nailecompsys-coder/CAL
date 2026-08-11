#!/usr/bin/env python3
"""Dump uiautomator hierarchy texts/descs with tap centers."""
import re
import subprocess
import sys

subprocess.check_call(
    ["adb", "shell", "uiautomator", "dump", "/sdcard/ui.xml"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
xml = subprocess.check_output(["adb", "shell", "cat", "/sdcard/ui.xml"], text=True)

# Split into node tags
nodes = re.findall(r"<node [^>]+/>", xml)
print(f"=== NODES ({len(nodes)}) ===")
for node in nodes:
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', node))
    t = attrs.get("text", "")
    d = attrs.get("content-desc", "")
    bounds = attrs.get("bounds", "")
    clickable = attrs.get("clickable", "false")
    if not t and not d:
        continue
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not m:
        continue
    x1, y1, x2, y2 = map(int, m.groups())
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    label = t or d
    print(f"click={clickable} ({cx},{cy}) {label!r}")

warn_pat = re.compile(
    r"left the composition|Could not load|CancellationException|StandAloneCoroutine|JobCancellation",
    re.I,
)
warns = []
for node in nodes:
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', node))
    for key in ("text", "content-desc"):
        val = attrs.get(key, "")
        if val and warn_pat.search(val):
            warns.append(val)
if warns:
    print("=== WARNINGS ON SCREEN ===")
    for w in warns:
        print(w)
else:
    print("=== WARNINGS ON SCREEN === none")

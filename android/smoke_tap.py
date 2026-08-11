#!/usr/bin/env python3
"""Find a UI node by text/desc and tap its center, or tap raw coords.

Note: Compose often omits clickable=true; coordinate taps still work.
Do not send KEYCODE_BACK from the root activity — it leaves CAL for the launcher.
"""
import argparse
import re
import subprocess
import sys
import time


def dump_xml() -> str:
    subprocess.check_call(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/ui.xml"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return subprocess.check_output(["adb", "shell", "cat", "/sdcard/ui.xml"], text=True)


def nodes(xml: str):
    for node in re.findall(r"<node [^>]+/>", xml):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', node))
        bounds = attrs.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        yield {
            "text": attrs.get("text", ""),
            "desc": attrs.get("content-desc", ""),
            "clickable": attrs.get("clickable", "false") == "true",
            "bounds": (x1, y1, x2, y2),
            "center": ((x1 + x2) // 2, (y1 + y2) // 2),
            "class": attrs.get("class", ""),
        }


def find_node(xml: str, needle: str, exact: bool = False):
    needle_l = needle.lower()
    candidates = []
    for n in nodes(xml):
        label = n["text"] or n["desc"]
        if not label:
            continue
        hay = label.lower()
        ok = hay == needle_l if exact else needle_l in hay
        if ok:
            candidates.append(n)
    if not candidates:
        return None
    # Prefer clickable, then larger area
    candidates.sort(
        key=lambda n: (
            0 if n["clickable"] else 1,
            -(n["bounds"][2] - n["bounds"][0]) * (n["bounds"][3] - n["bounds"][1]),
        )
    )
    return candidates[0]


def tap(x: int, y: int):
    subprocess.check_call(["adb", "shell", "input", "tap", str(x), str(y)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="text/desc to tap, or x,y")
    ap.add_argument("--exact", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.2)
    args = ap.parse_args()

    xml = dump_xml()
    if args.list:
        for n in nodes(xml):
            label = n["text"] or n["desc"]
            if not label:
                continue
            print(f"{n['center']} click={n['clickable']} {label!r}")
        return

    if not args.target:
        print("need target", file=sys.stderr)
        sys.exit(2)

    if re.fullmatch(r"\d+,\d+", args.target):
        x, y = map(int, args.target.split(","))
        print(f"tap raw ({x},{y})")
        tap(x, y)
    else:
        n = find_node(xml, args.target, exact=args.exact)
        if not n:
            print(f"NOT FOUND: {args.target}", file=sys.stderr)
            sys.exit(1)
        x, y = n["center"]
        label = n["text"] or n["desc"]
        print(f"tap {label!r} @ ({x},{y}) clickable={n['clickable']} bounds={n['bounds']}")
        tap(x, y)

    time.sleep(args.sleep)
    # print post-state summary
    xml2 = dump_xml()
    labels = []
    for n in nodes(xml2):
        label = n["text"] or n["desc"]
        if label:
            labels.append(label)
    print("AFTER:", " | ".join(labels[:40]))
    for w in labels:
        if re.search(
            r"left the composition|Could not load|CancellationException|JobCancellation",
            w,
            re.I,
        ):
            print("WARNING_ON_SCREEN:", w)


if __name__ == "__main__":
    main()

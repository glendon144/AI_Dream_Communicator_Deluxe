#!/usr/bin/env python3
import sys, re, pathlib

USAGE = "Usage: update_version.py <version> [root_dir=.]"

def main():
    if len(sys.argv) < 2:
        print(USAGE, file=sys.stderr); raise SystemExit(1)
    version = sys.argv[1]
    root = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path(".")
    candidates = [
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "modules/__init__.py",
        "modules/version.py",
        "modules/pikit/__init__.py",
        "pikit/__init__.py",
    ]

    changed = False

    def sub_text(text: str) -> str:
        # pyproject.toml / setup.py style: version = "x"
        text = re.sub(r'(^\s*version\s*=\s*")[^"]+(")', r'\g<1>' + version + r'\2', text, flags=re.M)
        # setup.cfg style: version = x
        text = re.sub(r'(^\s*version\s*=\s*)([^\s#]+)', r'\g<1>' + version, text, flags=re.M)
        # python: __version__ = "1.20"  or  'x'
        text = re.sub(r'(__version__\s*=\s*[\'"])[^\'"]+([\'"])', r'\g<1>' + version + r'\2', text)
        return text

    for rel in candidates:
        p = root / rel
        if p.exists() and p.is_file():
            src = p.read_text(encoding="utf-8")
            out = sub_text(src)
            if out != src:
                p.write_text(out, encoding="utf-8")
                print("Updated", p)
                changed = True

    # If nothing changed, try a broader search for __version__ in Python files
    if not changed:
        for p in root.rglob("*.py"):
            try:
                src = p.read_text(encoding="utf-8")
            except Exception:
                continue
            out = re.sub(r'(__version__\s*=\s*[\'"])[^\'"]+([\'"])', r'\g<1>' + version + r'\2', src)
            if out != src:
                p.write_text(out, encoding="utf-8")
                print("Updated", p)
                changed = True

    if not changed:
        print("No files updated. You may need to add your own paths.", file=sys.stderr)
        raise SystemExit(2)

    print("Done.")

if __name__ == "__main__":
    main()

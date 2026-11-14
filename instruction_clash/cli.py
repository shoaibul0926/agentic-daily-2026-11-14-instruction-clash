import argparse, json, sys
from .core import analyze


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="instruction-clash",
        description="Detect contradictions and loading gaps across agent instruction files.")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    a = ap.parse_args(argv)
    r = analyze(a.path)
    if a.json:
        print(json.dumps({**r, "findings": [f.__dict__ for f in r["findings"]]}, indent=2))
    else:
        if not r["files"]:
            print("No agent instruction files found.")
        else:
            print("Instruction files:", ", ".join(r["files"]))
            print("\nWhat each agent actually receives:")
            for ag, fs in r["effective"].items():
                print(f"  {ag:12} <- {', '.join(fs)}")
            print()
        for f in r["findings"]:
            print(f"[{f.severity.upper():5}] {f.kind}: {f.message}")
        if not r["findings"]:
            print("No clashes found.")
    errs = sum(f.severity == "error" for f in r["findings"])
    warns = sum(f.severity == "warn" for f in r["findings"])
    return 1 if errs or (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())

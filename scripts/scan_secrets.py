"""Conservative source scan. Report locations only, never secret values."""
import re
import subprocess
from pathlib import Path

PATTERNS = [
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    re.compile(r"(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def main():
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root).decode().split("\0")
    findings = []
    for name in paths:
        path = root / name
        if not name or not path.is_file():
            continue
        if path.name == ".env" or path.suffix in {".db", ".sqlite", ".sqlite3"}:
            findings.append(f"{name}: forbidden runtime artifact")
        try:
            for line, value in enumerate(path.read_text().splitlines(), 1):
                if any(pattern.search(value) for pattern in PATTERNS):
                    findings.append(f"{name}:{line}: possible credential")
        except UnicodeDecodeError:
            continue
    print("\n".join(findings) if findings else "PASS: no recognized credentials or runtime databases in tracked/unignored source.")
    print("Scope: working source, not Git history; heuristic scan is not a security certification.")
    raise SystemExit(bool(findings))


if __name__ == "__main__":
    main()

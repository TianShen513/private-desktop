"""Build a dependency-free application archive with the sandbox recipe included."""

from pathlib import Path
import hashlib
import shutil
import tempfile
import zipapp

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def main() -> None:
    DIST.mkdir(exist_ok=True)
    archive = DIST / "private-desktop.pyz"
    with tempfile.TemporaryDirectory(prefix="private-desktop-package-") as temporary:
        target = Path(temporary)
        shutil.copytree(ROOT / "src" / "private_desktop", target / "private_desktop",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (target / "__main__.py").write_text(
            "from private_desktop.cli import main\nraise SystemExit(main())\n", encoding="utf-8",
        )
        zipapp.create_archive(target, archive, compressed=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (DIST / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Built {archive.name} ({archive.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

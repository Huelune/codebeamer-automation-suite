from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


_NUMBER = r"(?:0|[1-9][0-9]*)"
_VERSION_PATTERN = re.compile(rf"^(?P<version>{_NUMBER}\.{_NUMBER}\.{_NUMBER})$")
_TAG_PATTERN = re.compile(
    rf"^v(?P<version>{_NUMBER}\.{_NUMBER}\.{_NUMBER})"
    rf"(?P<rc>-rc\.(?P<rc_number>{_NUMBER}))?$"
)


@dataclass(frozen=True)
class ReleaseTag:
    tag: str
    version: str
    rc_number: int | None

    @property
    def is_prerelease(self) -> bool:
        return self.rc_number is not None


def parse_release_tag(tag: str) -> ReleaseTag:
    """Parse a supported stable or release-candidate Git tag."""
    match = _TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(
            "release tag must match vX.Y.Z or vX.Y.Z-rc.N without leading zeroes"
        )

    rc_number = match.group("rc_number")
    return ReleaseTag(
        tag=tag,
        version=match.group("version"),
        rc_number=int(rc_number) if rc_number is not None else None,
    )


def read_release_version(version_file: str | Path) -> str:
    path = Path(version_file)
    version = path.read_text(encoding="utf-8").strip()
    if _VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"VERSION must contain an X.Y.Z version: {version!r}")
    return version


def validate_release_tag(tag: str, version_file: str | Path) -> ReleaseTag:
    release_tag = parse_release_tag(tag)
    version = read_release_version(version_file)
    if release_tag.version != version:
        raise ValueError(
            f"tag base version {release_tag.version!r} does not match VERSION {version!r}"
        )
    return release_tag


def write_github_output(path: str | Path, release_tag: ReleaseTag) -> None:
    values = {
        "artifact_version": release_tag.tag,
        "prerelease": str(release_tag.is_prerelease).lower(),
        "release_tag": release_tag.tag,
        "version": release_tag.version,
    }
    with Path(path).open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Codebeamer Automation Suite release metadata."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate-tag",
        help="validate a release tag against the repository VERSION file",
    )
    validate_parser.add_argument("--tag", required=True)
    validate_parser.add_argument("--version-file", default="VERSION")
    validate_parser.add_argument("--github-output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "validate-tag":
        try:
            release_tag = validate_release_tag(args.tag, args.version_file)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"release metadata validation failed: {exc}") from exc

        if args.github_output:
            write_github_output(args.github_output, release_tag)
        print(
            f"validated {release_tag.tag}: version={release_tag.version}, "
            f"prerelease={str(release_tag.is_prerelease).lower()}"
        )
        return 0

    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

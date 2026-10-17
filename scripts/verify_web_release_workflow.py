"""Fail closed when the release-branch image workflow loses a safety contract."""

from pathlib import Path
import sys


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "siftalpha-web-arm64.yml"


def require(source, fragment):
    if fragment not in source:
        raise ValueError(f"missing required workflow contract: {fragment}")


def reject(source, fragment):
    if fragment in source:
        raise ValueError(f"forbidden workflow content: {fragment}")


def main():
    if not WORKFLOW.is_file():
        raise ValueError(f"workflow is missing: {WORKFLOW.relative_to(WORKFLOW.parents[2])}")
    source = WORKFLOW.read_text(encoding="utf-8")
    for fragment in (
        "release/siftalpha-web-v1",
        "packages: write",
        "attestations: write",
        "id-token: write",
        "docker/setup-qemu-action@v3",
        "docker/setup-buildx-action@v3",
        "platforms: linux/arm64",
        "ghcr.io/${{ github.repository_owner }}/siftalpha-web",
        "type=raw,value=sha-${{ github.sha }}",
        "type=raw,value=v1.0.0-sha-${{ github.sha }}",
        "org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}",
        "org.opencontainers.image.revision=${{ github.sha }}",
        "io.siftalpha.build.run-id=${{ github.run_id }}",
        "io.siftalpha.build.ref=${{ github.ref_name }}",
        "actions/attest-build-provenance@v2",
        "siftalpha-web-build-manifest",
        "$GITHUB_STEP_SUMMARY",
        "DIGEST",
        "SOURCE_COMMIT",
        "RUN_ID",
        "RUN_URL",
        "PLATFORM",
        "push: true",
    ):
        require(source, fragment)
    for fragment in (
        "workflow_dispatch",
        "ssh ",
        "appleboy/ssh",
        "cloudflare",
        "docker compose",
        "docker-compose",
        "docker system prune",
        ":latest",
        "latest=true",
    ):
        reject(source.lower(), fragment)
    if "pull_request:" in source:
        raise ValueError("phase-one workflow must not build from pull requests")
    print("release workflow contract: ok")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(f"release workflow contract: {exc}", file=sys.stderr)
        raise SystemExit(1)

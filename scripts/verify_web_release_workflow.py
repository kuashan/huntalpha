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
        "runs-on: ubuntu-24.04-arm",
        "docker/setup-buildx-action@v3",
        "platforms: linux/arm64",
        "ghcr.io/${{ github.repository_owner }}/siftalpha-web",
        "type=raw,value=sha-${{ github.sha }}",
        "type=raw,value=v1.1.6-sha-${{ github.sha }}",
        "org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}",
        "org.opencontainers.image.revision=${{ github.sha }}",
        "org.opencontainers.image.version=V1.1.6",
        "io.siftalpha.build.run-id=${{ github.run_id }}",
        "io.siftalpha.build.ref=${{ github.ref_name }}",
        "provenance: mode=max",
        "Verify OCI BuildKit provenance",
        "docker buildx imagetools inspect",
        "verify_buildkit_provenance.py",
        "siftalpha-web-build-manifest",
        "$GITHUB_STEP_SUMMARY",
        "DIGEST",
        "SOURCE_COMMIT",
        "RUN_ID",
        "RUN_URL",
        "PLATFORM",
        "SOURCE_REF",
        "WORKFLOW_NAME",
        "buildkit-oci-slsa",
        "push: true",
    ):
        require(source, fragment)
    # Only the official release branch may trigger automatic builds.
    # Manual dispatch remains available for recovery or verification.
    expected_triggers = (
        "push:\n"
        "    branches:\n"
        "      - release/siftalpha-web-v1\n"
        "  workflow_dispatch:"
    )
    triggers = source.split("\non:\n", 1)[1].split("\npermissions:", 1)[0].strip()
    if triggers != expected_triggers:
        raise ValueError("release workflow triggers must be official push or manual dispatch")
    for fragment in (
        "attestations: write",
        "id-token: write",
        "actions/attest-build-provenance@v2",
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
        raise ValueError("release workflow must not build from pull requests")
    print("release workflow contract: ok")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(f"release workflow contract: {exc}", file=sys.stderr)
        raise SystemExit(1)

"""Fail-closed checks for BuildKit OCI provenance attached to a GHCR image."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise SystemExit(message)


def normalize_provenance(value):
    # buildx exposes the predicate for current versions, while registry-level
    # reads may still return the SLSA wrapper or the in-toto statement.
    if isinstance(value, dict) and isinstance(value.get("SLSA"), dict):
        value = value["SLSA"]
    if isinstance(value, dict) and isinstance(value.get("predicate"), dict):
        value = value["predicate"]
    return value


def main() -> None:
    if len(sys.argv) != 9:
        fail("usage: verify_buildkit_provenance.py build-manifest oci-manifest provenance digest commit run_id source-ref workflow")

    build_manifest_path, oci_manifest_path, provenance_path, digest, commit, run_id, source_ref, workflow = sys.argv[1:]
    if not source_ref.startswith("refs/heads/"):
        fail("OCI provenance source ref is invalid")
    branch = source_ref.removeprefix("refs/heads/")
    manifest = load(build_manifest_path)
    oci_manifest = load(oci_manifest_path)
    provenance = normalize_provenance(load(provenance_path))
    if not isinstance(provenance, dict):
        fail("OCI provenance payload is not an object")

    if manifest.get("digest") != digest:
        fail("build manifest digest mismatch")
    descriptors = oci_manifest.get("manifests")
    if not isinstance(descriptors, list):
        fail("OCI image index is missing manifests")

    arm64 = [
        item
        for item in descriptors
        if item.get("platform", {}).get("os") == "linux"
        and item.get("platform", {}).get("architecture") == "arm64"
    ]
    if not arm64:
        fail("OCI image index has no linux/arm64 manifest")
    arm64_digests = {item.get("digest") for item in arm64}
    linked_attestations = [
        item
        for item in descriptors
        if item.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest"
        and item.get("annotations", {}).get("vnd.docker.reference.digest") in arm64_digests
    ]
    if not linked_attestations:
        fail("BuildKit provenance attestation is not linked to the linux/arm64 manifest")

    legacy_build_type = provenance.get("buildType")
    v1_build_definition = provenance.get("buildDefinition")
    if legacy_build_type == "https://mobyproject.org/buildkit@v1":
        fail("OCI BuildKit provenance v0.2 is unsupported because it lacks verified source identity")
    elif (
        isinstance(v1_build_definition, dict)
        and v1_build_definition.get("buildType")
        == "https://github.com/moby/buildkit/blob/master/docs/attestations/slsa-definitions.md"
        and isinstance(v1_build_definition.get("externalParameters"), dict)
        and isinstance(v1_build_definition.get("resolvedDependencies"), list)
        and isinstance(provenance.get("runDetails"), dict)
    ):
        # SLSA v1 moved BuildKit's fields under buildDefinition/runDetails.
        internal = v1_build_definition.get("internalParameters")
        expected_workflow_ref = (
            "kuashan/huntalpha/.github/workflows/siftalpha-web-arm64.yml@"
            f"{source_ref}"
        )
        if not isinstance(internal, dict) or any(
            (
                internal.get("github_repository") != "kuashan/huntalpha",
                internal.get("github_workflow") != workflow,
                internal.get("github_workflow_ref") != expected_workflow_ref,
                internal.get("github_workflow_sha") != commit,
                str(internal.get("github_run_id")) != run_id,
                internal.get("github_ref") != source_ref,
                internal.get("github_event_name") not in {"push", "workflow_dispatch"},
            )
        ):
            fail("OCI BuildKit provenance source identity mismatch")
    else:
        fail("OCI provenance is not BuildKit SLSA provenance")

    expected_tag = f"sha-{commit}"
    version_tag = f"v1.1.6-sha-{commit}"
    tags = manifest.get("tags")
    def has_tag(candidate: str) -> bool:
        return any(tag == candidate or tag.endswith(f":{candidate}") for tag in tags or [])

    if not isinstance(tags, list) or not has_tag(expected_tag) or not has_tag(version_tag):
        fail("build manifest tags do not identify the source commit")
    if manifest.get("image") != "ghcr.io/kuashan/siftalpha-web":
        fail("build manifest image repository mismatch")
    if manifest.get("source_commit") != commit:
        fail("build manifest commit mismatch")
    if str(manifest.get("run_id")) != run_id:
        fail("build manifest Run ID mismatch")
    if manifest.get("ref") != branch or manifest.get("source_ref") != source_ref:
        fail("build manifest source ref mismatch")
    if manifest.get("workflow") != workflow:
        fail("build manifest workflow mismatch")
    if manifest.get("platform") != "linux/arm64":
        fail("build manifest platform mismatch")

    print(f"buildkit provenance: digest={digest} commit={commit} run_id={run_id}")


if __name__ == "__main__":
    main()

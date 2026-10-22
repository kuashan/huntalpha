#!/usr/bin/env python3
"""Tests binding BuildKit provenance to the reviewed Actions workflow run."""

import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
VERIFIER = ROOT / "deployment" / "web-admin" / "lib" / "verify_buildkit_provenance.py"
DIGEST = "sha256:" + "a" * 64
COMMIT = "e6320b7cde26ac03611905c5823ac758e60e6e38"
RUN_ID = "424242"
SOURCE_REF = "refs/heads/release/siftalpha-web-v1"
WORKFLOW = "SiftAlpha Web CI and ARM64"
WORKFLOW_PATH = ".github/workflows/siftalpha-web-arm64.yml"
FOOTER_SOURCE = (ROOT / "frontend/src/components/SiteVersionFooter.vue").read_text(encoding="utf-8")
VERSION_MATCH = re.search(r"(?m)^const version = ['\"](V\d+\.\d+\.\d+)['\"]$", FOOTER_SOURCE)
if VERSION_MATCH is None:
    raise ValueError("site footer release version missing")
VERSION = VERSION_MATCH.group(1).lower()


class BuildkitProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.manifest_path = root / "manifest.json"
        self.oci_manifest_path = root / "oci-manifest.json"
        self.provenance_path = root / "provenance.json"
        self.manifest_path.write_text(
            json.dumps(
                {
                    "image": "ghcr.io/kuashan/siftalpha-web",
                    "digest": DIGEST,
                    "source_commit": COMMIT,
                    "run_id": RUN_ID,
                    "run_url": f"https://github.com/kuashan/huntalpha/actions/runs/{RUN_ID}",
                    "ref": "release/siftalpha-web-v1",
                    "source_ref": SOURCE_REF,
                    "workflow": WORKFLOW,
                    "platform": "linux/arm64",
                    "tags": [f"sha-{COMMIT}", f"{VERSION}-sha-{COMMIT}"],
                }
            ),
            encoding="utf-8",
        )
        self.oci_manifest_path.write_text(
            json.dumps(
                {
                    "manifests": [
                        {
                            "digest": "sha256:" + "b" * 64,
                            "platform": {"os": "linux", "architecture": "arm64"},
                        },
                        {
                            "digest": "sha256:" + "c" * 64,
                            "annotations": {
                                "vnd.docker.reference.type": "attestation-manifest",
                                "vnd.docker.reference.digest": "sha256:" + "b" * 64,
                            },
                            "platform": {"os": "unknown", "architecture": "unknown"},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    def _provenance(self, workflow_sha=COMMIT, event_name="push"):
        return {
            "buildDefinition": {
                "buildType": "https://github.com/moby/buildkit/blob/master/docs/attestations/slsa-definitions.md",
                "externalParameters": {"request": {"args": {"platforms": ["linux/arm64"]}}},
                "resolvedDependencies": [],
                "internalParameters": {
                    "github_repository": "kuashan/huntalpha",
                    "github_workflow": WORKFLOW,
                    "github_workflow_ref": f"kuashan/huntalpha/{WORKFLOW_PATH}@{SOURCE_REF}",
                    "github_workflow_sha": workflow_sha,
                    "github_run_id": RUN_ID,
                    "github_ref": SOURCE_REF,
                    "github_event_name": event_name,
                },
            },
            "runDetails": {"builder": {"id": "https://github.com/moby/buildkit"}, "metadata": {}},
        }

    def _run(self, provenance):
        self.provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                str(self.manifest_path),
                str(self.oci_manifest_path),
                str(self.provenance_path),
                DIGEST,
                COMMIT,
                RUN_ID,
                SOURCE_REF,
                WORKFLOW,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_accepts_provenance_bound_to_expected_workflow_run(self):
        result = self._run(self._provenance())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_manual_workflow_dispatch_provenance(self):
        result = self._run(self._provenance(event_name="workflow_dispatch"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_stale_or_unrelated_version_tag(self):
        # Provenance must match the site version from this exact source tree.
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["tags"][1] = f"v0.0.0-sha-{COMMIT}"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self._run(self._provenance())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("build manifest tags do not identify the source commit", result.stderr)

    def test_rejects_unexpected_workflow_event(self):
        result = self._run(self._provenance(event_name="pull_request"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OCI BuildKit provenance source identity mismatch", result.stderr)

    def test_rejects_provenance_from_a_different_workflow_source_commit(self):
        result = self._run(self._provenance(workflow_sha="0" * 40))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OCI BuildKit provenance source identity mismatch", result.stderr)

    def test_rejects_legacy_provenance_without_source_identity(self):
        result = self._run(
            {
                "buildType": "https://mobyproject.org/buildkit@v1",
                "invocation": {},
                "metadata": {},
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OCI BuildKit provenance v0.2 is unsupported", result.stderr)


if __name__ == "__main__":
    unittest.main()

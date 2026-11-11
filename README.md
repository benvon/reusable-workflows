# reusable-workflows
Reusable GitHub Actions workflows for `benvon/*`.

Current families:

- `go-quality.yml`: standardized Go PR and main-branch quality check
- `go-goreleaser-release.yml`: tag-driven GoReleaser publish flow
- `release-policy.yml`: Conventional Commit PR title validation and `release:*` label sync
- `release-tag.yml`: automatic semver tag creation on merges to `main`
- `aws-infra-quality.yml`: standardized quality flow for the AWS jump-host repos
- `just-quality.yml`: standardized macOS `just`-driven quality flow
- `macos-script-release.yml`: tag-driven macOS packaging and GitHub release flow
- `docker-image-quality.yml`: standardized Docker image validation flow
- `docker-image-release.yml`: tag-driven Docker publish and GitHub release flow

This repo also self-hosts its own automation through wrapper workflows:

- `repo-quality.yml`: validates the reusable workflow files with `actionlint` and `yamllint`
- `repo-release-policy.yml`: applies the same Conventional Commit and `release:*` labeling policy used by caller repos
- `repo-release-tag.yml`: creates a semver tag on merges to `main` or via manual dispatch
- `repo-publish-release.yml`: turns pushed `v*` tags into GitHub Releases with generated notes

Automatic releases call the publisher directly after tagging. Tags pushed with
`GITHUB_TOKEN` do not trigger another push workflow, so callers should connect
their publisher using the reusable tagger's outputs rather than relying on a
second tag event. The tagger exposes `should_release`, `tag`, `sha`, and `created`.
Gate publication on `should_release == 'true'`, including when `created` is
`false`: rerunning a failed release reuses the tag and retries publication.
Existing GitHub Releases are successful no-ops. Direct `v*` tag pushes still
invoke this repository's publisher.

For example, a caller in this repository can connect the jobs as follows:

```yaml
jobs:
  release-tag:
    uses: ./.github/workflows/release-tag.yml
    permissions:
      contents: write
      pull-requests: read
    with:
      caller_event_name: ${{ github.event_name }}
      caller_sha: ${{ github.sha }}
      manual_release_type: ${{ github.event.inputs.release_type || '' }}
  publish-release:
    needs: release-tag
    if: needs.release-tag.outputs.should_release == 'true'
    uses: ./.github/workflows/repo-publish-release.yml
    permissions:
      contents: write
    with:
      release_tag: ${{ needs.release-tag.outputs.tag }}
```

Other repositories can use pinned references to these workflows or connect their
own publisher to the same outputs. The Docker, GoReleaser, and macOS publishers
still use the caller's ref; pass the resolved tag to an explicitly tag-aware
publisher rather than invoking those workflows from a main-branch event.

Local validation (Python with `yamllint`/PyYAML, Node.js, `actionlint` 1.7.12,
and ShellCheck 0.11.0 on PATH):

```sh
actionlint
yamllint .
python -m unittest discover -s tests -v
```

The intended branch-protection checks for caller repos are:

- `quality`
- `release-policy`

The intended branch-protection checks for this repo are:

- `quality / quality`
- `release-policy / release-policy`

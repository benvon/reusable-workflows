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

The intended branch-protection checks for caller repos are:

- `quality`
- `release-policy`

The intended branch-protection checks for this repo are:

- `quality / quality`
- `release-policy / release-policy`

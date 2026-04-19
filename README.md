# reusable-workflows
Reusable GitHub Actions workflows for `benvon/*`.

Current families:

- `go-quality.yml`: standardized Go PR and main-branch quality check
- `go-goreleaser-release.yml`: tag-driven GoReleaser publish flow
- `release-policy.yml`: Conventional Commit PR title validation and `release:*` label sync
- `release-tag.yml`: automatic semver tag creation on merges to `main`
- `aws-infra-quality.yml`: standardized quality flow for the AWS jump-host repos
- `terraform-module-quality.yml`: standardized Terraform module PR quality flow
- `just-quality.yml`: standardized macOS `just`-driven quality flow
- `macos-script-release.yml`: tag-driven macOS packaging and GitHub release flow
- `docker-image-quality.yml`: standardized Docker image validation flow
- `docker-image-release.yml`: tag-driven Docker publish and GitHub release flow

The intended branch-protection checks are:

- `quality`
- `release-policy`

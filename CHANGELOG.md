# Changelog

All notable changes to this project will be documented in this file.

This project follows semantic versioning once it leaves alpha. While it remains
pre-release, minor versions may still adjust public API and wire contracts.

## Unreleased

- Added a `just` command surface for local lint, test, package smoke, and full
  check workflows.
- Added a package smoke script that builds the wheel, installs it into an
  isolated target, verifies public API imports, and checks dependency metadata
  for absent DRF/drf-spectacular dependencies.
- Added a release checklist with alpha, beta, and stable readiness criteria.

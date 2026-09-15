<!--
File: CHANGELOG.md
Summary: Chronological record of notable Personal Finance application changes.
Modified by: Eric Freeman
Last modified: 2026-09-15
-->

# Changelog

This project follows the structure of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Native iPhone companion application that loads Personal Finance over its private Tailscale URL.
- Unique shared application icon for the iPhone and macOS launchers.
- Repository-wide documentation guidance for file headers, functions, setup, and change history.

### Changed

- Local development now binds to localhost by default.

## [2026-09-15]

### Added

- CSV transaction reconciliation with one-to-one matching and corrective import/delete actions.
- Budget calendar with month selection and transaction detail popovers.
- Full macOS launcher bundle, automatic service startup, and Tailscale-only remote access.

### Fixed

- Reconciliation of duplicate CSV rows and normalized transaction descriptions.
- Balance calculations after deleting checkpointed transactions.
- Generation of recurring budget items for the upcoming month.
- macOS conflicts with the system-owned port 5000 service.

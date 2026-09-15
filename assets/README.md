<!--
File: assets/README.md
Summary: Documents the shared visual assets used by Personal Finance applications.
Modified by: Eric Freeman
Last modified: 2026-09-15
-->

# Shared Assets

`PersonalFinanceIcon.png` is the 1024×1024 full-bleed RGB master icon. It depicts layered transaction
records crossed by a green reconciliation and progress path. Derived iOS icon sizes live in the
iPhone asset catalog, and the macOS ICNS derivative lives under `scripts/macos/resources`.

Regenerate every platform derivative from this master whenever the icon changes. Do not add rounded
corners or transparency to the source; Apple applies the platform-specific icon mask.

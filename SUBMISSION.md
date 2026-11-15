# Decky marketplace submission status

This repository contains the current maintainer-tested Touchscreen Toggle source.
No marketplace pull request has been submitted for this plugin.

## Blocking eligibility question

The official new-plugin PR template, checked on November 14, 2026, requires:

> Generative AI was NOT used to write a majority of the code I am submitting.

Most of this implementation was generated with AI assistance, followed by tests
and maintainer device testing. That declaration cannot truthfully be checked.
Formatting, review or publishing the source does not change its authorship.
Resolve eligibility with Decky maintainers before presenting a store submission as
ready. Do not assert an exception based only on other accepted AI-assisted plugins.

Official template:
https://github.com/SteamDeckHomebrew/decky-plugin-database/blob/main/.github/PULL_REQUEST_TEMPLATE/plugin_addition.md

Official guidance:
- https://wiki.deckbrew.xyz/en/plugin-dev/submitting-plugins
- https://wiki.deckbrew.xyz/en/plugin-dev/review-and-testing

## Remaining submission work

- [x] Source, tests, fixed helper, installer, licenses and build lockfile are included.
- [x] Current UI and helper were installed on the maintainer's Legion Go S/Bazzite 45.
- [x] Maintainer confirmed the current UI meets the requested behavior.
- [ ] Obtain a maintainer eligibility decision with accurate AI disclosure.
- [ ] Verify fresh prerequisite installation on SteamOS without weakening OS protections.
- [ ] Verify operation on both SteamOS Stable and Beta, as required by the developer checklist.
- [ ] Obtain a third-party SteamOS Stable/Beta test report; do not self-attest it.
- [ ] Complete store `publish` metadata with real tags, description and image asset.
- [ ] Add an actual screenshot of the current plugin UI, with no private information.
- [ ] Verify uniqueness or explain alternative functionality versus existing plugins.
- [ ] Where available, test two other submitted plugins and link feedback; the current template describes this community step as optional/lower-priority without it.

The current `plugin.json` intentionally retains the tested runtime metadata. It
contains no fabricated screenshot URL or unverified compatibility claims.

## Planned database PR

Once eligible and tested, fork `SteamDeckHomebrew/decky-plugin-database` and add:

1. One `.gitmodules` entry pointing to this public source repository.
2. One gitlink at `plugins/touchscreen-toggle`, pinned to the exact reviewed commit.

Keep the source, tests and helper in this repository, not copied into the database
PR. Record the actual source commit in the PR and complete the current official
template honestly. Use the upstream-requested branch and submission process as
verified at submission time. No Decky Loader changes are required for this design.

## Installation boundary

The runtime ZIP does not install the helper or grant permissions. The included
administrator-approved prerequisite installer is still required. That requirement
must be visible to reviewers and testers; it is not an automatic store install.

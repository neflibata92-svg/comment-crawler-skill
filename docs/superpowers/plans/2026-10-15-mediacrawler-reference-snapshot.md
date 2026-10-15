# MediaCrawler Reference Snapshot and Neflibata Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pinned, reference-only snapshot of five MediaCrawler platform adapters, document its provenance and limits, and make `Neflibata` the Git author on every public branch in this repository.

**Architecture:** Copy only the five platform directories' top-level Python files, the changed configuration file, and the upstream license from the pinned upstream commit into `references/mediacrawler-source/`. Apply the repository's existing browser and Zhihu pagination transformations to the copy only. Update project provenance and usage docs, commit with the GitHub account's noreply address, then rewrite author metadata in an isolated mirror and update all four branch refs with guarded force pushes.

**Tech Stack:** Python 3, Git, GitHub REST API, MediaCrawler upstream source.

**Spec:** `docs/superpowers/specs/2026-10-15-mediacrawler-reference-snapshot-design.md`

## Global Constraints

- Pin upstream to `NanmiCoder/MediaCrawler` commit `19c956c962726f5ba6de338a04f82e6c4716b054`.
- Include five platforms only: Douyin, Bilibili, Weibo, Zhihu, Tieba; exclude XHS and test fixtures.
- Keep the snapshot reference-only; runtime collection continues to use external `MEDIACRAWLER_HOME`.
- Preserve the upstream `LICENSE` exactly and keep upstream attribution separate from `Neflibata`.
- Set Git author name/email to `Neflibata <294585395+neflibata92-svg@users.noreply.github.com>` for every resulting commit; leave committer metadata, dates, messages, and existing trees unchanged.
- Thirteen existing commits have GPG signatures. Rewriting their author metadata invalidates those signatures; the user explicitly accepted that loss on 2026-10-15. Do not claim the rewritten commits remain signed.
- Rewrite `main`, `feature/comment-analysis`, `feature/mediacrawler-platforms`, and `feature/xiaohongshu-comments`; push with exact `--force-with-lease` values captured from current remote heads.
- Do not download real platform data, account profiles, cookies, or media.

## Review Focus

- Snapshot accidentally includes XHS, fixtures, or runtime data — inventory copied paths and reject any path outside the specified five platform `.py` sets, config, and license.
- The patcher no longer matches upstream — run the existing transformations against the pinned source and parse each transformed Python file.
- Root MIT license is mistaken as covering MediaCrawler — preserve the upstream license byte-for-byte and add an explicit notice.
- History rewrite changes file trees or commit messages — compare old/new commit maps, trees, messages, and dates before any push.
- History rewrite invalidates existing commit signatures — the user has accepted the impact for all 13 signed commits; verify the rewritten history does not claim those signatures remain valid.
- A branch changes after the initial audit — refresh remote heads and require `--force-with-lease` against the exact captured SHA for all four refs.

---

### Task 1: Build the pinned reference snapshot

**Files:**
- Create: `references/mediacrawler-source/media_platform/douyin/*.py`
- Create: `references/mediacrawler-source/media_platform/bilibili/*.py`
- Create: `references/mediacrawler-source/media_platform/weibo/*.py`
- Create: `references/mediacrawler-source/media_platform/zhihu/*.py`
- Create: `references/mediacrawler-source/media_platform/tieba/*.py`
- Create: `references/mediacrawler-source/config/base_config.py`
- Create: `references/mediacrawler-source/LICENSE`
- Create: `references/mediacrawler-source/README.md`
- Create: `references/mediacrawler-source/NOTICE.md`

**Interfaces:**
- Consumes: `/tmp/comment-crawler-mediacrawler-upstream-review` at the pinned upstream SHA.
- Uses: `scripts/comment_crawler/collectors/mediacrawler.py` helpers `_replace_bool_assignment`, `_remove_anti_detection`, and `_patch_zhihu_comment_limit`.
- Produces: a partial, non-installable reference copy; it is not imported by the collector.

- [x] Copy only top-level Python files from the five upstream platform folders, plus `config/base_config.py` and the exact upstream `LICENSE`.
- [x] Apply the existing browser-mode and anti-detection removals to the five copied `core.py` files; apply the existing pagination change to copied Zhihu `core.py` and `client.py`.
- [x] Add local `README.md` and `NOTICE.md` with source URL, pinned SHA, snapshot date, exact local transformations, reference-only status, Neflibata attribution, upstream copyright, and license restrictions.
- [x] Verify copied file inventory excludes `xhs`, `test_data`, profiles, data, and dependencies; compare `LICENSE` byte-for-byte with the pinned upstream file.
- [x] Parse all copied `.py` files in memory and assert the intended browser and Zhihu pagination settings are present.

### Task 2: Update repository documentation

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `PROVENANCE.md`
- Modify: `references/mediacrawler.md`
- Modify: `docs/superpowers/specs/2026-10-15-mediacrawler-reference-snapshot-design.md`
- Create: `docs/superpowers/plans/2026-10-15-mediacrawler-reference-snapshot.md`

**Interfaces:**
- Consumes: snapshot directory and its `NOTICE.md`.
- Produces: clear links from project docs to the reference snapshot, with runtime checkout boundaries unchanged.

- [x] Add “Maintainer: Neflibata” to the root README and explain that runtime still uses the external `MEDIACRAWLER_HOME` checkout.
- [x] Set the package author metadata in `pyproject.toml` to `Neflibata`; preserve the root MIT copyright notice.
- [x] Replace the provenance statement that no MediaCrawler source is included with the exact snapshot scope, source commit, local changes, and upstream-license boundary.
- [x] Update the MediaCrawler guide to distinguish the reference snapshot from the external runtime checkout and keep the five-platform collection instructions intact.
- [x] Review docs for any claim that the snapshot is the user's missing optimized checkout or is independently executable.

### Task 3: Commit the source and documentation changes

**Files:**
- Add/modify: files produced by Tasks 1–2.

**Interfaces:**
- Consumes: verified source snapshot and updated docs.
- Produces: one local feature-branch commit authored by `Neflibata` using the account noreply email.

- [x] Run `git diff --check` and inspect `git status --short` and `git diff --stat`.
- [x] Commit the snapshot and docs on `feature/mediacrawler-platforms` with author and committer name `Neflibata`; do not push yet.

### Task 4: Rewrite all branch authors in an isolated mirror

**Files:**
- Modify: temporary mirror refs only.
- Do not modify: remote refs until the validation step passes.

**Interfaces:**
- Consumes: current four remote branch tips plus the local snapshot commit.
- Produces: rewritten branches where all commits have the Neflibata author identity; committer metadata remains intact.

- [x] Create a disposable mirror from `origin`, record the four original branch SHAs, and fetch the local snapshot commit object into the mirror.
- [x] Advance only the mirror's `feature/mediacrawler-platforms` ref to the local snapshot commit.
- [x] Use built-in `git filter-branch --env-filter` in the mirror to change author name/email across all four heads; do not install new dependencies. The 13 prior GPG signature headers were removed as approved.
- [x] Verify the result has 21 commits, four expected branch names, a single author identity, and unchanged trees/messages/committer metadata/author dates for all 20 prior commits; verify the added snapshot commit has the Neflibata identity.
- [x] Refresh remote heads and confirm they still match the recorded original SHAs before pushing.

### Task 5: Push and verify GitHub refs

**Files:**
- Remote refs: `main`, `feature/comment-analysis`, `feature/mediacrawler-platforms`, `feature/xiaohongshu-comments`.

**Interfaces:**
- Consumes: verified rewritten mirror and original remote SHAs.
- Produces: four updated GitHub branches and a synchronized local feature checkout.

- [x] Push all four rewritten refs with explicit `--force-with-lease=refs/heads/<branch>:<original-sha>` guards.
- [x] Verify remote branch heads match the rewritten mirror; GitHub REST associates the snapshot commit with `neflibata92-svg` and reports author name `Neflibata`.
- [x] Fetch rewritten branches into the current workspace and synchronize local branch refs without discarding uncommitted work. The separate comment-analysis worktree's untracked plan file was preserved.
- [x] Run final `git status --short --branch`, `git diff --check`, and author-count checks across all resulting refs.

The final verification and completed-plan record are committed as a separate Neflibata-authored follow-up after the 21-commit history rewrite; this keeps the rewritten source snapshot commit unchanged.

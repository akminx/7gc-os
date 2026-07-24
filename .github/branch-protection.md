# Branch protection checklist (GitHub)

Local hooks are bypassable (`--no-verify`). Mirror the gate in CI and lock
the default branch so trust-critical review cannot be skipped when someone
is tired.

Run once per repo (Settings → Branches → Branch protection rules), or via
`gh api` if you prefer automation. captain-init does **not** apply these
automatically — they need repo admin rights.

## Required settings

- [ ] Require a pull request before merging
- [ ] Require status checks to pass: `check-all` / `check-all-python` /
      `check-all-node` (whatever `.github/workflows/check-all.yml` defines)
- [ ] Require branches to be up to date before merging (optional but good)
- [ ] Require review from Code Owners (uses `CODEOWNERS`)
- [ ] Dismiss stale pull request approvals when new commits are pushed
- [ ] Do **not** allow author self-approval (GitHub: disable bypass for
      admins on critical repos if you can live with it)
- [ ] Block force pushes and deletions on the default branch

## Trust-critical extra

For repos with money / authz / safety surface: require at least one
approving review from someone other than the PR author, even when CI is
green. CODEOWNERS on paths listed in `review-policy.yaml` is the mechanism.

## Verify

```sh
gh api "repos/{owner}/{repo}/branches/{branch}/protection" --jq .
```

If this 404s, protection is not configured yet.

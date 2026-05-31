# Release Checklist — FunKit 1.20

- [ ] Ensure working tree is clean (`git status`).
- [ ] Update version to 1.20 (use `scripts/bump_version.sh 1.20` or `scripts/update_version.py 1.20`).
- [ ] Verify `/health` and index & doc pages render.
- [ ] `git tag -a v1.20 -m "FunKit 1.20 — Universal Reader"`
- [ ] `git push && git push origin v1.20`
- [ ] Create GitHub release; attach PR kit zip; paste Release Notes.

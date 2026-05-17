---
name: worktree-manager
description: "Trigger: worktree, parallel branches, multiple features. Manage isolated git worktrees for parallel development without losing work."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

# Worktree Manager

## Hard Rules

1. **NEVER remove a worktree without explicit user confirmation** — worktree content is lost permanently
2. **ALWAYS list existing worktrees before creating a new one** — see what's already open
3. **NEVER assume the current directory is the main repo** — verify with `git rev-parse --show-toplevel`
4. **ALWAYS use `.worktrees/` subdirectory for local worktrees** — never create bare worktrees in arbitrary locations
5. **ALWAYS verify `.worktrees/` is git-ignored before first use** — if not, add to .gitignore and commit
6. **Store open worktrees in memory via mem_save** — so context survives across sessions

## Decision Gates

| Situation | Action |
|-----------|--------|
| User asks for new worktree | List current worktrees first, confirm path, then create |
| User asks to "switch to X" | Identify which worktree, do NOT create if it doesn't exist |
| Worktree already exists at path | Offer to navigate or continue work, NOT recreate |
| User mentions specific worktree path | Use that exact path — do not derive or guess |
| No .worktrees/ directory | Create it + verify it's git-ignored before use |
| User wants to remove worktree | Show what will be lost, require explicit confirmation |

## Execution Steps

### Before Creating Any Worktree

1. Run `git worktree list` — show all existing worktrees
2. Ask user which branch/path they want (or derive from request context)
3. If path already exists → report "worktree already exists at X" and stop
4. If path doesn't exist → proceed to create

### Creating a Worktree

```powershell
# 1. Verify .worktrees/ exists and is ignored
git check-ignore -q .worktrees 2>$null
if ($LASTEXITCODE -ne 0) {
    # NOT ignored - must fix first
    Add-Content -Path .gitignore -Value ".worktrees/"
    git add .gitignore
    git commit -m "chore: ignore .worktrees directory"
}

# 2. Create worktree with new branch
git worktree add ".worktrees/$BRANCH_NAME" -b "$BRANCH_NAME"
```

### Tracking Open Worktrees

After creating or opening a worktree, save to memory:

```
mem_save with:
- title: "Worktree open: {branch-name}"
- type: discovery
- topic_key: worktrees/open-worktrees
- content: **What**: {branch-name} worktree at {full-path}
           **Why**: User requested for parallel development
           **Where**: {full-path}
```

### When User Asks to Open/Work on Another Feature

1. **DO NOT remove current worktree** — ask user where to put the new one
2. List existing worktrees → user picks path or says "create new"
3. If existing worktree → confirm "Navigate to {path}?"
4. If new worktree → create alongside existing, not replace

## Output Contract

After any worktree operation, report:
- Current worktree location and branch
- All open worktrees (from `git worktree list`)
- What changed (created / navigated / removed)

## References

- `solo-dev-workflow` skill — git workflow best practices
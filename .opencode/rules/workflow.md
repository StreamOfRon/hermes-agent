# Development Workflow

## Branch Strategy

This repository uses a multi-branch workflow to manage contributions:

- **`main`** - Clean mirror of the upstream repository (`upstream/main`). Do not commit directly to this branch.
- **`dev`** - Active development branch with integrated features. **Always create new branches from here.**

## Creating New Branches

When starting new work, always branch from `dev`:

```bash
git checkout dev
git pull origin dev
git checkout -b feat/your-feature-name
```

## Branch Lifecycle

**Important: Do NOT delete branches until they have been merged into `upstream/main`.**

This ensures:
- You can continue to reference the branch if you need to make changes during review
- The PR remains open and active until accepted by upstream
- You can easily rebase if upstream requests changes

## Submitting Changes Upstream

1. Create your feature branch from `dev`
2. Make your changes and commit
3. Push to your fork
4. Open a pull request from `your-fork/feat/your-feature-name` to `upstream/main`
5. **Keep the branch alive** until the PR is merged

## Rebasing

Periodically sync `dev` with upstreamPeriodically sync `dev` with upstream:

```bash
git checkout main
git pull upstream main
git push origin main
git checkout dev
git rebase main
```

## Branch Management: NEVER Merge Dev to Main

**CRITICAL:** This repository follows a specific fork workflow where `main` is kept as a clean mirror of upstream. **NEVER merge `dev` into `main` directly.**

**Why:**
- `main` should only contain upstream code plus fork-specific infrastructure (like GitHub workflows)
- `dev` contains active development work integrated from feature branches
- This prevents polluting `main` with work-in-progress code
- Scheduled workflows (like `.github/workflows/sync-and-rebase.yml`) only run from the default branch (`main`)

**The workflow:**
1. Create feature branches from `dev`
2. Work in the feature branch
3. Merge feature branches back to `dev` for integration
4. When ready to submit upstream, rebase `dev` onto updated `main`, then open PR from `dev` to upstream

**Important:** The `.github/workflows/sync-and-rebase.yml` file is intentionally isolated to `main` branch only, as it requires being on the default branch to run on schedule.

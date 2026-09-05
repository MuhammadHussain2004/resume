# Resume — auto-synced with GitHub activity

This repo holds Muhammad Hussain Khan Lodhi's resume (`Muhammad_Hussain_Resume.tex` /
`.pdf`) and a GitHub Actions workflow that keeps it up to date automatically.

## How it works

Every day at 08:00 PKT (and on-demand via **Actions → Sync Resume with GitHub
Activity → Run workflow**), a job:

1. Pulls a snapshot of `github.com/MuhammadHussain2004`: profile bio, the
   special profile README (if any), and all owner repos (description,
   topics, languages, README excerpt, stars, last-pushed date).
2. Sends that snapshot plus the current resume `.tex` to Gemini, with
   instructions that **any** section — Summary, Education, Certifications,
   Experience, Projects, Technical Skills — may be updated, but only where
   the GitHub data gives clear, unambiguous evidence for that specific
   change. A section with no supporting evidence is left untouched; nothing
   is fabricated, and the contact header is never touched.
3. Before accepting Gemini's answer, a plain Python check (`validate_structure`
   in `scripts/sync_resume.py`) mechanically verifies it didn't break the
   rules — see **Safety checks** below. Only if that passes does the workflow
   recompile the PDF and commit both files back to this repo. If it fails,
   the run exits with a red ❌ in the Actions tab and nothing is committed —
   the resume is left exactly as it was.

So the latest resume — `.tex` and `.pdf` — always lives at the root of this
repo. Whenever you need it, just come here and download
[`Muhammad_Hussain_Resume.pdf`](./Muhammad_Hussain_Resume.pdf).

## Safety checks (no fabricated content, nothing structural breaks)

Every run is checked against the actual fetched GitHub data before it's
allowed to touch the repo:

- The LaTeX preamble (fonts, margins, custom commands — everything before
  `\begin{document}`) must come back byte-for-byte identical. The template
  can never be altered.
- The contact-info header (name/phone/email/links) must come back
  byte-for-byte identical.
- The resume must still have exactly six sections, in the same order:
  Summary, Education, Certifications, Experience, Projects, Technical Skills.
- Every *new* Technical Skills entry must appear verbatim (case-insensitive)
  somewhere in the fetched GitHub data (a repo description, README, topic,
  or language) — if it can't be traced back to real data, the run is
  rejected rather than guessed at. (This caught a real case: an earlier run
  once added "Redux Toolkit" with no repo actually using Redux; the fix
  removed it and added this check so it can't happen silently again.)
- Every project link must be a real repo URL from this GitHub account —
  never an invented one.
- The prompt also instructs the model to keep the resume to one page and
  never fabricate dates, employers, or metrics — the checks above are the
  mechanical backstop for the parts of that which can actually be verified
  in code; the rest still relies on the model following instructions, so an
  occasional spot-check of the diff (`git log -p`) is still worthwhile.

## One-time setup (required before the automation will run)

The workflow needs two repository secrets. Add them under
**Settings → Secrets and variables → Actions → New repository secret**, or
via the CLI:

```bash
# A token with "repo" scope, so the workflow can read your private repos too
# (the default GITHUB_TOKEN can only see this one repo). Easiest: reuse your
# already-authenticated gh CLI token (it already has the repo scope):
gh secret set GH_READ_TOKEN --repo MuhammadHussain2004/resume --body "$(gh auth token)"

# Or, for a token that won't be affected by `gh auth logout` later, create a
# dedicated one at https://github.com/settings/tokens (repo scope) and run:
#   gh secret set GH_READ_TOKEN --repo MuhammadHussain2004/resume

# Your Gemini API key, from https://aistudio.google.com/apikey
gh secret set GEMINI_API_KEY --repo MuhammadHussain2004/resume
```

Both secrets are already set on this repo (as of the automation being wired
up). If the Gemini key ever rotates, just re-run that last command with the
new value.

Until both secrets are set, the scheduled runs will fail at the
"Analyze GitHub activity" step (or simply be skipped) — commit and push your
other repos as normal in the meantime, then add the secrets whenever you're
ready to switch the automation on.

## Local editing

You can still edit `Muhammad_Hussain_Resume.tex` by hand any time — the next
scheduled run treats your manual edits as the new baseline and only adjusts
what the GitHub data actually warrants. To get the PDF back in sync with a
manual edit immediately (instead of waiting for the next scheduled run), go
to **Actions → Sync Resume with GitHub Activity → Run workflow** and check
"Skip Gemini analysis, just recompile the PDF" — that recompiles and commits
the PDF from whatever `.tex` is currently in the repo, with no AI call.

# Sync ecosystem conversation history

This file is a durable project-memory record of the work discussed in the AI chat. It is intentionally kept inside the repository so a future assistant can understand the architecture and previous decisions without relying on the original chat session. It does not contain OAuth secrets, refresh tokens, client-secret JSON, or private keys.

## Original context

- The initial conversation database referenced by the user was `C:\Users\mhkpl\.gemini\antigravity-ide\conversations\b1b828bb-08da-4627-a624-f89dd1d704e7.db`.
- The user wanted the resume, portfolio, GitHub profile README, Google Drive, OneDrive, and local copies to remain current with minimum manual work.
- The user repeatedly clarified that normal GitHub pushes and scheduled automation should do the routine work; explicit changes are requested in chat.

## Automation decisions

1. GitHub Actions is the cloud source of automation. It must work while the laptop is off.
2. The resume repository is the vetted source for resume facts and the compiled PDF.
3. The portfolio reads the latest resume source/PDF and GitHub project data. It keeps committed generated JSON fallbacks so external API failures do not break a deploy.
4. The local Windows scheduled task is only a bridge for local/OneDrive/locally mounted Drive copies. Cloud workflows cannot write directly to a powered-off laptop.
5. Google Drive uses OAuth refresh-token credentials stored only in GitHub Secrets. OAuth test-user, redirect URI, and app-publishing issues were diagnosed during setup.
6. Retry/catch-up behavior is required. Existing outputs must not be deleted when an external API, Gemini, Drive, or GitHub request fails.

## Repository layout

- Resume source: `D:\Programming-Development\auto-sync-profiles\my-resume`
- Portfolio: `D:\Programming-Development\auto-sync-profiles\my-portfolio`
- Resume GitHub repository: `MuhammadHussain2004/resume`, branch `master`
- Portfolio GitHub repository: `MuhammadHussain2004/My-Portfolio`, branch `main`
- Local resume sync task: `C:\Users\mhkpl\AppData\Local\ResumeSync\sync-resume.ps1`
- Personal parent workspace: `D:\Programming-Development\auto-sync-profiles`

## Resume workflow history

- The resume workflow analyzes GitHub activity and repositories, updates the resume source when evidence supports a change, compiles `Muhammad_Hussain_Resume.pdf`, uploads it to Google Drive, and dispatches portfolio/profile synchronization.
- The resume technical-skills section was reviewed several times. PHP, Shell, and Framer Motion were removed when there was no current evidence; they may be re-added when a future repository or verified source supports them.
- Confirmed technologies used across the projects include JavaScript, TypeScript, JSX, HTML5, CSS3, Python, Java, C/C++, SQL, Node.js, npm, Express.js, React, React DOM, Vite, Next.js, React Router, Tailwind CSS, Context API, Redux Toolkit, Socket.IO, bcrypt, JWT, CORS, dotenv, Multer, MongoDB, MongoDB Atlas, Mongoose, PostgreSQL, Sequelize, MySQL, Turso/libSQL, SQL Server, Docker, Nodemon, ESLint, GitHub Actions, Postman, SonarQube, Mocha/Chai, Vercel, GitHub Pages, Railway, and Netlify.
- Resume skills use professional category names: Languages, Core Computer Science, Frontend Technologies, Backend Technologies, Databases and ORMs, Developer Tools, Cloud and Deployment, and Soft Skills. Avoid awkward slash-heavy labels.
- The resume currently contains verified proof for the 10Pearls 10Shine internship certificate and the IBM Full-Stack JavaScript Developer certificate. SMIT is represented as training unless a certificate URL is added.

## Portfolio workflow history

- `scripts/generate-projects.mjs` analyzes public GitHub repositories, scores software-engineering/full-stack evidence, filters tutorial/practice repositories, and generates the top six project cards plus screenshots/stats.
- `scripts/sync-resume.mjs` downloads the latest PDF from the resume repository.
- `scripts/sync-content.mjs` reads the resume `.tex`, uses Gemini only to adapt already-vetted facts into portfolio JSON, and preserves the previous fallback on failure.
- Portfolio generated content is stored under `src/generated/`. The UI reads generated content instead of duplicating facts in components.
- A dedicated `Certifications` section was added to the portfolio. It derives cards from timeline entries with a certificate tag or certificate link, so verified certificates remain synchronized with resume content.
- Portfolio navigation now includes About, Work, Skills, Experience, Certifications, and Contact.

## Project-selection requirements

- Analyze all complete public repositories, not only descriptions.
- Prefer meaningful full-stack/software-engineering applications with frontend, backend, database, authentication, deployment, tests, or other production evidence.
- Rank projects using code/dependency evidence, recency, completeness, and relevance.
- If a strong project lacks a description, generate an accurate description from repository evidence only; never invent technologies.
- Preserve user-authored sections and only rewrite generated/marked sections.

## Latest change in this repository

- Resume spacing was adjusted after the user reviewed a PDF screenshot: more top breathing room, better section spacing, more distance between experience/project entries, and less aggressive negative vertical spacing.
- The Summary was refined with ATS-friendly but evidence-based keywords: RESTful APIs, JWT authentication, role-based access control, database-backed applications, deterministic recommendation engines, and automated testing.
- The latest resume source change was pushed to `master` in commit `075a532`; the compiled PDF was then committed by the successful workflow as `23c3723`.
- After the user reported that the first spacing revision became two pages, the vertical budget was rebalanced: readable top/header and section gaps remain, while the compiled PDF is confirmed as exactly one page. Source commit: `a47a3d5`; compiled PDF commit: `a974fb5`.
- 2026-10-05: The user reported that the Technical Skills section looked clipped and requested a complete, professional one-page ATS resume. Summary, experience bullets, project descriptions, coursework, and certificate wording were tightened without removing the required sections or evidence-based keywords. The final rendered PDF was visually checked: all Technical Skills categories are visible with balanced whitespace and readable section gaps. Source commit: `cb4a38e`; automatic analysis commit: `b874da9`; compiled PDF commit: `a2c26c0`; workflow run `37238089789` completed successfully and confirmed `1 page`.

## Operational rules for future assistants

- After every future chat task that changes this ecosystem, append a dated entry to this file and mirror the same update in the portfolio repository's `docs/CONVERSATION_HISTORY.md`. Record what changed, why, validation results, and commit/workflow IDs.
- Read this file and the repository `AGENTS.md`/`GEMINI.md` before editing.
- Keep the resume source and compiled PDF synchronized after a source edit.
- Keep portfolio generated JSON and UI synchronized with the resume source.
- Run repository lint/build checks before pushing.
- Do not commit secrets or OAuth files.
- Do not overwrite remote changes; fetch/rebase first if a push is rejected.
- When a new certificate is added, include its official proof URL in the resume source so the portfolio can display it automatically.

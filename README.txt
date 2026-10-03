Python-to-Fortran playground (local prototype)
=============================================

The existing GitHub Pages homepage translates in the browser. The optional
/run/ page adds execution using a local service; the homepage remains available.

Execution preview on Windows
----------------------------
  cd C:\python\python-to-fortran-playground
  python xvendor.py
  npm ci
  python xeditor.py
  python xrun.py
Then open http://127.0.0.1:8766/run/. Python packages used by submitted programs
must be installed in the Python environment running xrun.py. gfortran must be
on PATH, or pass --compiler C:\path\to\gfortran.exe. --timeout 30 limits each
program run; translation/compilation has a separate 180-second limit.

Run Python, Run Fortran, Run Both, Compare outputs, and Stop are supported.
Python and Fortran stdout/stderr and timings appear separately; compilation
diagnostics remain visible. Translate and optional 750 ms live translation
never run submitted programs. Each operation uses fresh temporary directories,
with Python and Fortran files separated. Edits invalidate prior results; late
results are discarded. Source and generated Fortran are not stored persistently.

The service verifies and extracts the same pinned vendor bundle used by the
browser, never a local xp2f.py checkout. Fortran builds use the upstream CLI
and matching helpers. Comparison ignores whitespace and compares numeric
tokens with absolute/relative tolerance 1e-10; random draws are not replayed.
Program timings include process startup, and compilation is timed separately.
The default compiler command is gfortran -ffree-line-length-none, applying
to both generated code and bundled helpers that contain lines over 132 columns.
For local --compiler overrides, include the appropriate flags for that compiler.

This service is for TRUSTED LOCAL USE: programs run with your Windows account's
permissions. It binds only to 127.0.0.1, checks Host and Origin, requires a
session token, limits input/output and concurrent jobs, and cancels process
trees. These controls are not a security sandbox. Do not expose the service
through a tunnel or reverse proxy. Public execution needs disposable isolated
jobs, CPU/memory/disk/process limits, disabled networking, and rate limits.
GitHub Pages can publish /run/, but execution there remains unavailable until
a sandboxed service is configured. The local preview works immediately.

Execution checks (gfortran and NumPy required for the integration examples):
  python -m unittest discover -s tests -p test_execution.py

Start on Windows:
  cd C:\python\python-to-fortran-playground
  python xvendor.py
  npm ci
  python xeditor.py
  python xserve.py
Then open http://127.0.0.1:8765/ in a modern browser. Internet access is needed
to load Pyodide from jsDelivr. Do not open index.html as a file:// URL.

Source policy
-------------
upstream.json pins the PUBLIC GitHub commit and Pyodide release. xvendor.py
downloads that commit directly from GitHub, never the local transpiler tree.
It bundles the root Python modules, Fortran helper sources, and any root
license notices. No upstream source is patched. The browser verifies the
bundle's SHA-256, displays the commit, and downloads matching runtime helpers.
Generated vendor files are ignored by Git; deployments rebuild them.

To update: set commit in upstream.json to a full published commit SHA, run
xvendor.py and the smoke tests, and commit the pin change. Never mix individual
upstream files from different revisions. A transpiler push does not update
this separate project automatically.

On-demand upstream updates
--------------------------
In the playground repository, choose Actions > Update transpiler > Run
workflow on main. Leave commit blank for the latest published p2f main commit,
or supply a complete published SHA to select a specific version or roll back.
The workflow freezes that SHA, rebuilds the bundle, runs the Python and
WebAssembly/browser-adapter tests, builds the Pages artifact, deploys the
matching Modal service, checks its revision/isolation and three real jobs,
commits the tested pin, and publishes Pages. It does not change the parent
transpiler repository. No schedule or update-on-page-load is enabled.

One-time setup in the PLAYGROUND repository:
  Settings > Secrets and variables > Actions > New repository secret
  Add MODAL_TOKEN_ID and MODAL_TOKEN_SECRET from a Modal API token belonging
  to the workspace hosting p2f-playground-execution. Never commit the token.
  https://modal.com/docs/guide/continuous-deployment describes these secrets.
The workflow requests contents:write and Pages/OIDC permissions. Repository
rules must allow its github-actions bot to push pin commits to main; protected
branches requiring a PR may reject this. It also honors github-pages environment
approval rules. The existing service URL in site/run/service.json must be valid.
Keep Modal usage budgets/spend limits set: image builds and checks cost compute,
and each successful update uses three jobs from the public execution quota.

Both deployment workflows share a concurrency lock. Normal pushes still run
Test and deploy playground; pushes made by GITHUB_TOKEN do not trigger another
workflow, so Update transpiler publishes its own tested artifact directly.
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
After a successful automated update, run git pull --ff-only in your local
playground checkout before making further changes.

Testing failures leave the pin and live deployments unchanged. If deployment
or verification fails before the pin is pushed, the workflow attempts to restore
the previous service. Inspect logs if restoration itself fails. Modal and Pages
cannot switch atomically: /run/ may briefly refuse a revision mismatch while
Pages updates (the translation-only page stays usable). If pin publication
succeeds but Pages fails, the tested new service/pin remain; run Test and deploy
playground to retry Pages. Cancellation/timeouts may require manual recovery;
avoid cancelling after service deployment has begun. An advancing main branch
or a rejected push aborts publication rather than overwriting anyone's changes.

Implementation
--------------
site/ contains static HTML/CSS/JavaScript plus a Python translation adapter.
Page loading starts one persistent module Worker with Pyodide. The adapter
warms the transpiler with a fixed trivial translation before enabling Translate.
The adapter
calls transpile_file directly with flat=True, a fixed input filename, source
text, and the pinned python.f90. It does not call the CLI, compile, or run the
submitted program. Diagnostics are rendered as text, not HTML.

Input is limited to 100 KB. Initialization and each translation have separate
180-second limits. Successful translations and normal diagnostics retain the
worker. Cancel, timeouts, or fatal errors terminate it; click Initialize to
restart. Initialization time and translation-only time are shown separately.
Before each job, the adapter restores snapshots of upstream module/class state
and uses a fresh temporary directory. Compiled functions and two read-only
vendored-runtime registries stay cached. No upstream source is modified.
The interpreter and downloaded sources remain available between jobs.

Limitations
-----------
Single-file input only; no uploads, arbitrary CLI flags, multi-file projects,
or persistent source storage. Numerical output is not executed or verified.
The helpers ZIP contains all root Fortran helpers, not just those used by the
current result. Some are alternative platform implementations: do not compile
every helper indiscriminately. Use the transpiler project's build guidance.
Runtime loading requires network access. A worker keeps the UI responsive but
does not impose a hard browser memory limit. Browser compatibility and visual
QA must be checked in an actual browser before a public launch.

Checks
------
  npm ci
  npm test
The smoke tests use the pinned Pyodide WebAssembly runtime in Node and the same
bridge.py as the website. They check examples, diagnostics, input limits, and
that a Python raise is translated rather than executed. Repeated submissions,
state reset, and temporary-file cleanup are checked too. A mocked UI test
checks worker reuse and recovery without launching a browser. These are not a full
browser or upstream regression suite.

Publishing later
----------------
Create a separate GitHub repository (suggested: python-to-fortran-playground).
Initialize this directory with main as its default branch and push the source.
In that repository's Settings > Pages, select GitHub Actions as the source.
The included workflow builds the pinned bundle, runs smoke tests, and only
deploys after they pass. Use HTTPS; relative asset URLs support project Pages.
The translation-only site is published at
https://beliavsky.github.io/python-to-fortran-playground/ . The /run/ page is
included in the same Pages build. xrun.py serves trusted local executions;
xmodal.py deploys the optional hosted API.

Hosted execution with Modal
---------------------------
The account that deploys the API pays for visitors' executions. Modal's
published Starter plan currently includes $30/month of compute credits;
check current prices at https://modal.com/pricing . Before public deployment,
set a Workspace usage budget and spend limit in Modal's Usage & Billing page.
https://modal.com/docs/guide/budgets explains that usage budgets apply before
credits; spend limits cap net charges after credits. Job-count limits below
are not dollar spending caps, and API requests also consume resources.

Create a Modal account, then run on Windows:
  cd C:\python\python-to-fortran-playground
  python -m venv .venv-execution
  .venv-execution\Scripts\python.exe -m pip install -r requirements-execution.txt
  .venv-execution\Scripts\python.exe -m modal token new
  python xvendor.py
  .venv-execution\Scripts\python.exe -X utf8 xdeploy_service.py

Use xdeploy_service.py for later service updates too. It builds and publishes
an immutable, content-named job image from the local checkout before deploying
the API. The API only references that published image; it cannot upload local
files from inside its runtime container. Running modal deploy directly does
not build/publish a new job image.

Deployment prints an HTTPS origin ending in .modal.run. Configure the page:
  python xconnect_service.py https://YOUR-DEPLOYED-SERVICE.modal.run
This checks the API's health, pinned revision, and isolation configuration,
then writes site\run\service.json. Commit that file and push; the Pages build
publishes it. service.json contains a public endpoint URL, never credentials.
Modal account tokens stay outside the repository and submitted sandboxes.

The page fetches service.json on connection, verifies the API's pinned revision
against its vendor manifest, and sends jobs to that HTTPS API. The API accepts
the GitHub Pages origin and local preview origins. Each browser receives its
own temporary session token; jobs and cancellation are restricted to their
owner. CORS is a browser policy, not protection from automated clients.

Each execution runs as an unprivileged user in a new gVisor sandbox, with
networking blocked, no secrets or shared volumes, at most one physical CPU
core and 1 GiB memory, a 250-second sandbox lifetime, 30 seconds per program,
and the existing source/output limits. Unix limits cap individual files at
16 MiB, processes at 128, and open files at 128. The sandbox's root filesystem
quota is supplied by Modal; the file-size limit is not a total-disk quota.
The image includes gfortran, NumPy, SciPy, pandas, and the verified pinned
transpiler/helpers. Visitors do not need these installed on their computers.

The API admits two simultaneous jobs, 30 starts per address per ten minutes,
and 100 total starts per UTC day (including translation/live requests).
Limits and ownership survive an API restart in Modal's persistent Dict.
The single API container serializes state changes. Unfinished provisioning
reserves a slot conservatively for ten minutes if interrupted. Do not delete
the state Dict to reset usage. Review limits in xpublic_api.py before changing
them; deployed API traffic and image builds have their own costs.

Input is sent to the sandbox but not stored in the state Dict. Results and job
metadata expire five minutes after completion and are pruned on subsequent
requests. Modal may retain sandbox output logs under its account log policy.
The service scales down when idle. Localhost previews always use xrun.py,
even when service.json names the public API.

To stop public execution, stop p2f-playground-execution in the Modal dashboard.
The original translation-only playground remains independent.

Public API and hosted-connection checks:
  .venv-execution\Scripts\python.exe -m unittest discover -s tests -p test_public_api.py
  node tests/public_ui.mjs
  .venv-execution\Scripts\python.exe -X utf8 xcheck_service.py
These use a fake sandbox provider and check ownership, limits, CORS, expiry,
endpoint selection, HTTPS validation, and revision mismatch handling. A real
Modal deployment needs a live check before calling public execution operational.
xcheck_service.py uses three real jobs to check the unprivileged Python user
and matching Python/Fortran results for basic arithmetic and NumPy.

Local validation, 2026-10-02
----------------------------
All six Pyodide smoke checks passed. Both JavaScript entry points passed
node --check. All seven served endpoints (page, scripts, adapter, manifest,
and ZIPs) returned HTTP 200 with appropriate content types.
One measured run took 7.2 seconds to load the runtime and 63.9 seconds for
the first translation including transpiler initialization. Later translations
in that same interpreter took 0.36-0.44 seconds. The updated browser design
retains the interpreter and restores upstream state between translations;
the cold-start cost is paid once per worker instead of on every submission.
No connected browser was available for visual or click-through verification.
These measurements describe the original local prototype before deployment.

Editor features
---------------
Pages deployments run xsite.py to create _site with content-versioned URLs
for scripts, styles, editor dependencies, the worker, and its Python adapter.
This prevents a newly loaded page from using an older cached UI script (which
can leave new buttons inactive and line counters stuck at zero). Source files
in site are not modified. To preview the deployment artifact locally, run
python xsite.py, then python -m http.server 8766 --bind 127.0.0.1 --directory _site.
Check the build with python -m unittest discover -s tests -p test_site_build.py.

CodeMirror 5.65.20 is pinned in package-lock.json. xeditor.py bundles its
Python and Fortran modes, stylesheet, and MIT notice; no extra editor CDN is
needed. The workflow builds these assets after npm ci. After pulling these
changes locally, run npm ci and python xeditor.py, then refresh the page.
Editor loading is independent of translator initialization. If it fails,
plain textareas remain usable and Clear asks before discarding nonempty input.

The Python editor supports four-space Tab indentation, line numbers, and
Ctrl+Z (Cmd+Z on macOS). Clear is one undoable edit in the enhanced editor;
it also clears the translation and diagnostics and focuses Python input.
It does not restart the worker and remains available during a translation.
The Fortran editor remains read-only, with text selection and copying allowed.
Esc blurs the editor so keyboard users can move to the next control.
Both headings count physical lines including comments and blank lines; one
terminal newline does not add an extra line, and empty text has zero lines.

Persistent-worker validation, 2026-10-02
--------------------------------------
All 11 Pyodide checks and the mocked UI lifecycle checks passed. A measured
run used 5.6 seconds for runtime startup and 76.4 seconds for transpiler
initialization plus warm-up. The four translations then took 0.45-0.56 seconds
each, including the per-job state reset. Initialization runs when the page
loads; it is not repeated on each Translate click. Reloading the page or
restarting a cancelled worker still incurs initialization again.

Live translation
----------------
Enable the optional Live translation checkbox to translate the entire Python
buffer after a 750 ms typing pause. It is off by default. The persistent worker
checks Python completeness without executing it. Unfinished or invalid syntax
quietly waits; click Translate for explicit syntax diagnostics. Valid but
unsupported Python still reports the transpiler's diagnostic.

Editing, Clear, and loading examples remain available while translating.
Only one request runs at a time; edits coalesce into the newest pending buffer.
Old results cannot replace newer input. The previous Fortran stays visible,
marked stale, and Download is disabled until a current translation succeeds.
Clear removes both buffers' results. Turning live mode off cancels pending
automatic requests, but lets an in-flight request finish. Cancel and timeouts
stop the worker and pause live mode to prevent automatic restart loops.
No submitted program is ever executed or compiled, in either mode.

This is part of the existing playground, not a separate site. Its published
transpiler pin is unchanged. After committing and pushing this repository,
the existing GitHub Pages workflow tests and deploys the live-capable version.

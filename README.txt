Python-to-Fortran playground (local prototype)
=============================================

Separate project, not yet published to GitHub. Translation only: no compiler,
program execution, user accounts, or server-side translation endpoint.

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
No GitHub repository, remote, deployment, or public site has been created yet.
Review licensing and the public-facing limitations before publishing.

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
The website has not been publicly deployed.

Editor features
---------------
CodeMirror 5.65.20 is pinned in package-lock.json. xeditor.py bundles its
Python and Fortran modes, stylesheet, and MIT notice; no extra editor CDN is
needed. The workflow builds these assets after npm ci. After pulling these
changes locally, run npm ci and python xeditor.py, then refresh the page.
Editor loading is independent of translator initialization. If it fails,
plain textareas remain usable and Clear asks before discarding nonempty input.

The Python editor supports four-space Tab indentation, line numbers, and
Ctrl+Z (Cmd+Z on macOS). Clear is one undoable edit in the enhanced editor;
it also clears the translation and diagnostics and focuses Python input.
It does not restart the worker and is disabled during a translation.
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

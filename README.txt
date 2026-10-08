Python-to-Fortran playground (local prototype)
=============================================

The existing GitHub Pages homepage translates in the browser. The optional
/run/ page adds execution using a local service; the homepage remains available.

Built-in examples
-----------------
Both Python pages share 20 small single-file examples in a categorized selector:
Basics, NumPy, Statistics, Numerical methods, Linear algebra, and Simulation.
The original three demonstrations remain available; the additional examples
are short adaptations of files in the upstream examples/ directory, with a
source link and description shown beside the selector. The complete catalog
is kept in site/examples.mjs, so loading does not fetch a moving upstream file.

Choose an example, then click Load example. Replacing nonempty Python input
requires confirmation. Loading is undoable and pauses live translation; it
never translates, compiles, or runs automatically. Existing Fortran and results
remain visible but stale. The Fortran-only mode retains its separate examples.
The two random examples are labeled explicitly: even identical seed values
do not make Python and Fortran RNG streams agree, so Compare may report DIFF.
No example needs local data files or user modules; NumPy is the only third-party
Python dependency. Problem sizes are deliberately small.

Every example is checked against the pinned bundle in the browser-runtime smoke
test. tests/test_examples.py compiles and runs all of them with GNU Fortran,
compares deterministic output with Python, and checks that both random programs
run successfully. Helpers are precompiled once for this test group. Run it with:
  python -m unittest discover -s tests -p test_examples.py
Changing upstream.json requires revalidating this catalog; the examples are
not a claim that every upstream example or every optional compiler is supported.

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
The /run/ page also offers Intel Fortran (ifx), LLVM Flang, and LFortran
(all experimental) when the service advertises them. GNU remains the default;
compiler choices are fixed server-side
commands, not user-supplied command strings. Each result identifies its compiler.
An unavailable compiler is reported without silently falling back; select GNU
to retry. A real compilation failure is retained as a failure.
Python-only execution and translation do not require the selected compiler.

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
Each advertised Intel/LLVM Flang/LFortran compiler adds three validation jobs.

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

Intel support is a separate optional image. xdeploy_service.py first builds
and publishes GNU, then attempts an Intel image with compiler package
intel-oneapi-compiler-fortran-2025.3=2025.3.3-30 from Intel's signed APT repository.
The image must pass translated arithmetic, NumPy mean/std (python.f90), and
linear-solve (lapack_d.f90) comparisons before Intel is advertised. If installation
or these checks fail, deployment reports a warning and leaves GNU and Flang
unaffected.
Use --without-intel to explicitly skip Intel installation. GNU jobs always use
the smaller GNU image; all engines keep the same isolation/resource limits.
Intel's environment is initialized by a trusted wrapper, never by visitor input.
Installation follows https://www.intel.com/content/www/us/en/developer/tools/oneapi/fortran-compiler-download.html
and the software remains subject to Intel's applicable licence terms. No
separate compiler account token is passed to submitted jobs. Building the
optional image adds download/build time and Modal compute usage.

All compiler images precompile python.f90 and lapack_d.f90 once, separately
with the same options used by execution jobs. Each job copies the
object/module files into its own temporary directory; writable caches are
never shared between visitors. Source hashes, compiler version/options, and
artifact checksums must match before reuse. Missing or incompatible caches
fall back to ordinary helper compilation. Changing the pin or build scripts
selects a new runtime image and rebuilds the helpers. This reduces repeated
compilation time and Modal compute usage, not the number of jobs charged
against the service's daily allowance. Local preview without an image cache
continues to compile normally.

LLVM Flang has its own optional image, independent of Intel. It uses the
signed https://apt.llvm.org/bookworm/ LLVM 21 repository and pins flang-21 to
1:21.1.8~++20251221032947+2078da43e25a-1~exp1~20251221153113.67 (LLVM 21.1.8).
Neither the upstream transpiler nor helper sources are modified. The image
must compile both helpers and pass arithmetic, mean/std, LAPACK solve,
formatting, and random-number execution checks using its own precompiled
objects/modules before Flang is advertised. A failed Flang image does not
disable GNU or Intel. Use --without-flang to skip it; use both --without-intel
and --without-flang and --without-lfortran for a GNU-only deployment. These optional images add
build time and Modal usage. Visitors cannot supply arbitrary compiler flags.
Local preview detects flang-21, flang, or flang-new on PATH (LLVM Flang only).
To require Flang in hosted validation:
  .venv-execution\Scripts\python.exe -X utf8 xcheck_service.py --require-flang
Validation uses three GNU jobs plus three jobs for each advertised optional
compiler (twelve jobs when all four compilers are available).

LFortran uses an independent Conda image with conda-forge's Linux package
lfortran=0.66.0=hd7e4fe6_4, installed using Modal's micromamba support.
It is alpha software, not a promise that every translated program works.
Both helper sources are unchanged. Its fixed server-side compiler options are:
  lfortran --no-style-suggestions --no-color --implicit-interface --separate-compilation --legacy-array-sections
The first two options bound noisy diagnostics; --implicit-interface and
--legacy-array-sections support legacy LAPACK calls and sequence association.
--separate-compilation is essential: otherwise compiling python.f90 produces
a module file and a stub object, not the helper implementations needed to link.
The image precompiles both helpers and must pass the same arithmetic, NumPy,
LAPACK, formatting, and random-number execution checks as Flang. A failed image
is not advertised and does not disable the other compilers. Use
--without-lfortran to skip it. To require it during hosted validation:
  .venv-execution\Scripts\python.exe -X utf8 xcheck_service.py --require-lfortran
See https://docs.lfortran.org/en/installation/ for the recommended Conda setup.
Windows local execution additionally requires the initialized Visual Studio
compiler/linker environment; an unrelated GNU link.exe on PATH is not MSVC's
linker. The hosted Linux image does not require visitors to install these tools.
The reproducible test-only probe saves source hashes and compiler diagnostics:
  .venv-execution\Scripts\python.exe -X utf8 xprobe_lfortran.py --modal --out lfortran_results.json
This builds a test image and uses Modal compute; it does not publish an image
or deploy/change the live service. Local probing accepts --runtime PATH instead.

The parent python.f90 must include the portability fix that declares the string
argument before the result length in to_lower/to_upper. Older published pins
(including 51cb68b) fail Intel's helper compilation. Publish that parent fix,
select its commit with xupdate_upstream.py, and rebuild xvendor.py before
deployment. Do not patch the vendored sources; browser and service use the same
published bundle. This does not change the two functions' signatures or output.

Local preview can use Intel already installed and initialized on PATH; it
does not install Intel on your computer. For a strict hosted validation, run:
  .venv-execution\Scripts\python.exe -X utf8 xcheck_service.py --require-intel
Normal xcheck_service.py checks GNU and all advertised optional compilers. The
selector is confined to /run/; the translation-only page remains unchanged.

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
The translation-only site's Fortran editor remains read-only. On /run/,
the optional Edit Fortran mode enables editing and standalone compilation.
Esc blurs the editor so keyboard users can move to the next control.
Both headings count physical lines including comments and blank lines; one
terminal newline does not add an extra line, and empty text has zero lines.

Edit Fortran on /run/
--------------------
Enable Edit Fortran to modify a translation or enter an unrelated single-file
Fortran main program. Compile and Run Fortran uses that buffer unchanged,
without translating Python. Python input may be empty for this operation.
Run Both and Compare outputs execute Python and the edited Fortran, using
separate fresh working directories. Compiler selection applies as usual.

Live translation pauses while editing Fortran. Python edits and Clear do not
discard manual Fortran. Translate asks before replacing manual edits, and
Restore last translation asks before discarding edits. Turning edit mode off
does not discard changes. Results from older buffers cannot overwrite edits.
Download Fortran saves the current pane, including manual changes.

Programs using python_mod automatically link python.o and lapack_d.o, using
the selected compiler's verified precompiled cache when available. No helper
source is changed and no additional libraries (such as stdlib) are provided.
Declare your own real64/dp kinds as needed; normal Fortran USE rules apply.
Standalone code without python_mod does not link the helpers. Each language
has its own 100 KB source limit. All existing execution limits and sandbox
isolation remain in force; editing never automatically executes code.

After publishing the page, redeploy the execution service with
  .venv-execution\Scripts\python.exe xdeploy_service.py
The old service does not accept the new edit operations. Local previews use
the updated xrun.py immediately after restarting it. Check direct compilation:
  python -m unittest discover -s tests -p test_fortran_edit.py

Source tools: settings, local files, annotation suggestions
---------------------------------------------------------
Both Python playgrounds offer integer kinds (compiler default/int32/int64)
and Preserve comments. The pinned xp2f transpile API and CLI support int-kind.
Comment preservation is a playground display/output setting: disabling it
filters ordinary Fortran comments AFTER translation, retaining quoted ! text
and compiler directives. It does not disable source-comment inference hints
or change helper code. Settings are printed with results, validated server-side,
and never change a manually edited Fortran pane. These controls are hidden in
Fortran-only mode. The pinned upstream revision remains unchanged.

Load Python file is available on both pages. Load Fortran file is available
on /run/ and enables Edit Fortran automatically. Files are decoded locally as
UTF-8 (an optional BOM is accepted), limited to 100 KB, and confirmed before
replacing nonempty code. Invalid UTF-8/binary files report an error. Loading
preserves the other editor and pauses live translation. It never translates
or executes code. Download names follow the loaded filename where applicable.
No folders, multiple files, dependencies or data-file uploads are supported.

Suggest type annotations parses source without running it. Review the
read-only preview and diagnostics, then explicitly Apply suggestions or
Download annotated Python. Applying is undoable in the enhanced editor,
pauses live translation and never runs/translates source. A stale preview
cannot replace newer Python. This is Pyccel-compatible annotation syntax,
not a guarantee of Pyccel compilation or type correctness.

The playground uses its own small conservative helper rather than the older
xannotate_for_pyccel.py header rewriter. It inserts parameter annotations only
and verifies that the AST is otherwise unchanged. It preserves existing
annotations, inline bodies, multiline signatures, positional-only markers,
comments, Unicode and line endings. It refuses conflicting/unknown evidence
instead of widening types. Inference considers simple literals, singly-bound
module variables and NumPy array constructors at direct module-scope callers.
Nested/decorated/async/variadic functions, unresolved forwarding callers,
return annotations and complicated expressions are not inferred. Suggestions
are for review, not a proof: mutation, aliasing and dynamic Python remain
outside this limited analysis.

The translation-only page performs annotation analysis inside its existing
browser worker. /run/ sends annotation requests to the isolated hosted worker;
they consume the same job quota as other operations. Suggested Python appears
in the private job result and may appear in Modal's sandbox output logs, just
like generated Fortran. Input is not separately stored in the state Dict.
Local file selection alone does not send file contents anywhere.

Push the page changes and redeploy the service using xdeploy_service.py.
Against an older service, /run/ disables annotation/settings controls until
the service advertises source_tools support; local file loading still works.
Tests: node tests/source_tools.mjs and
  python -m unittest discover -s tests -p test_source_tools.py

Fortran-only playground
----------------------
Open /run/?mode=fortran for the dedicated Fortran layout, or toggle Fortran
only on /run/. Both entry points use the same page and execution service;
there is no extra repository or backend to maintain. The heading, examples
and full-width editor switch to Fortran, hiding Python input/output,
translation controls, and Run Both/Compare. Compiler choices, options, Run,
Stop, Download and compilation diagnostics remain available.

Fortran is editable automatically. A new empty pane receives a standalone
sum-of-squares example; nonempty code is never replaced on entry. Load example
and Clear operate on Fortran only and ask before replacing or deleting code.
Python code, output and timings survive switching, running Fortran and Clear.
Fortran-only requests send empty Python source. Returning to the combined
layout restores the previous Edit Fortran setting, retains Fortran changes,
and leaves live translation paused. The layout toggle is locked during a job.
Switching updates the mode query parameter without reloading the page.

This is a UI-only update: push this repository for the Pages workflow to
publish it. It uses the existing edit-mode API; no service redeployment is
needed if that API is already deployed. Check with node tests/fortran_only.mjs.

Compiler versions
-----------------
Compiler versions are exposed as compiler_versions in the session response and
compiler_version in compilation/rerun results for clients such as fortran-playground.
Hosted deployment reads the recorded helper-build banners once from each enabled
compiler image and passes them to the API; sessions never launch a version probe.
Local execution caches --version probes by trusted compiler command. An unavailable
version does not disable a compiler. Redeploy with xdeploy_service.py to publish
this metadata; existing clients may ignore the new fields.

User-code compiler options on /run/
----------------------------------
Choose Default, Debug, Optimized, or Strict when supported by the selected
compiler. Optional Extra warnings and advanced Fast math controls are enabled
only for compilers that offer them. The page shows the selected flags; build
diagnostics show the actual command. Default preserves existing behavior.
GNU Debug enables -fcheck=all and backtraces; Intel Debug enables -check all
and traceback. Flang Debug enables -O0 -g only, not bounds-checking promises.
Strict adds GNU pedantic/extra warnings, Intel extra warnings, or Flang pedantic
diagnostics; it no longer supplies a standard year. Clients may select a separate
standard (string year, or 'default') in compiler_options. Only years verified
against that image are advertised and accepted. GNU uses -std=fYEAR (f95 for
1995); Intel uses -stand f95/f03/f08/f18/f23 and reports conformance warnings.
These checks do not promise complete implementation of the selected standard.
Flang/LFortran standard flags are not offered yet. An older client without a
standard control can continue using default/debug/optimized/strict presets.
Standard flags are checked with cached helpers, recorded in their manifest and
passed through deployment metadata; no per-session hosted probes are needed.
LFortran currently offers Default and experimental --fast only.

Options are validated against compiler_options.py on both local and hosted
servers. There is no raw flags field, include/link path control, ABI-changing
kind option, or CPU-specific selection. Fast math is off by default and can
change numerical results. Intel Optimized explicitly uses -fp-model precise;
selecting Fast math overrides that. Some floating-point runtime behavior is
process-wide even though helper object code is not rebuilt.

These settings compile user Fortran, not python.f90 or lapack_d.f90. Helpers
retain their existing compiler-specific cache and fallback build settings;
debugging and standards checks do not instrument/check helper source. For
non-default options, xp2f translates without compiling, then the standalone
compile driver links the helpers with user code. Default keeps the original
single-call transpile/compile path. Translation-only operations ignore flags.
Hosted image builds verify every advertised preset/extra using cached helpers;
an optional compiler that fails verification remains unavailable.

References for the deliberately small subset:
  https://gcc.gnu.org/onlinedocs/gfortran/Debugging-Options.html
  https://www.intel.com/content/www/us/en/developer/articles/guide/porting-guide-for-ifort-to-ifx.html
  https://flang.llvm.org/docs/FlangCommandLineReference.html
  https://docs.lfortran.org/en/usage/

After committing/pushing these changes, redeploy the execution service:
  .venv-execution\Scripts\python.exe xdeploy_service.py
The new option controls stay disabled against an old service, which does not
advertise the catalog. Local previews need xrun.py restarted.

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

Fortran-only playground: compile and rerun
----------------------------------------
The separate fortran-playground frontend uses the same execution service.
fortran-compile builds submitted Fortran without executing it. An explicit
retain_executable request for fortran-compile or fortran-edit lets the sandbox
export a bounded executable before running the submitted program. The API keeps
the bytes privately and returns only an opaque session-owned build identifier.
fortran-run retrieves that build and runs it in a fresh, network-blocked sandbox
using its original compiler environment, without compilation or helper rebuilds.
No executable-upload endpoint is exposed. Other sessions cannot use a build.

Builds expire after at most five minutes (or session expiry), are invalidated by
a runtime-image change, and replace the previous build for the same session.
Limits: 4 MiB per executable, 32 retained builds globally. Expired storage is
cleaned on subsequent API requests. No idle sandbox is retained; run-created
files are not preserved. Existing concurrency, rate and daily limits apply to
each compilation and rerun. Existing Python playground operations are unchanged.

Redeploy with .venv-execution\Scripts\python.exe xdeploy_service.py before using
the new buttons. Session features advertise support; old services leave the new
frontend buttons disabled. No hosted deployment is performed by local tests.

#!/bin/bash
# Build a self-contained offline test harness for the ARTHA engine.
#
# This machine has no working Python interpreter, so the engine is executed
# under Pyodide (CPython compiled to WebAssembly) inside the browser. The whole
# backend is embedded into the generated HTML as a base64 tarball, which means
# an iteration costs one file write and one page reload.
#
#   usage: tools/mkharness.sh [entry_script]   # default: tools/harness_main.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTRY="${1:-tools/harness_main.py}"
OUT="${ARTHA_HARNESS_OUT:-/tmp/artha_harness.html}"
PYODIDE="https://cdn.jsdelivr.net/pyodide/v314.0.6/full/"

cd "$ROOT/backend"
TGZ="$(mktemp -t artha_pkg).tgz"
# COPYFILE_DISABLE stops BSD tar writing AppleDouble '._name' sidecar files,
# which are not UTF-8 and would otherwise be unpacked next to every module.
COPYFILE_DISABLE=1 tar czf "$TGZ" \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='._*' \
  artha tools tests 2>/dev/null

{
  cat <<HTMLEOF
<!doctype html><html><head><meta charset="utf-8"><title>ARTHA engine harness</title>
<style>
 body{background:#0d1117;color:#c9d1d9;font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;margin:0;padding:16px}
 pre{white-space:pre-wrap;word-break:break-word;margin:0}
 .ok{color:#3fb950}.bad{color:#f85149}.dim{color:#8b949e}
</style></head><body><pre id="out" class="dim">booting pyodide…</pre>
<script src="${PYODIDE}pyodide.js"></script>
<script id="pkg" type="text/plain">
HTMLEOF
  base64 -i "$TGZ" | tr -d '\n'
  cat <<HTMLEOF

</script>
<script>
window.__ARTHA_DONE__ = false;
window.__ARTHA_OUT__ = "";
(async () => {
  const out = document.getElementById("out");
  const show = (s, cls) => { out.textContent = s; if (cls) out.className = cls;
                             window.__ARTHA_OUT__ = s; };
  try {
    const py = await loadPyodide({ indexURL: "${PYODIDE}" });
    window.py = py;
    await py.loadPackage(["numpy"]);
    const bin = Uint8Array.from(atob(document.getElementById("pkg").textContent.trim()),
                                c => c.charCodeAt(0));
    py.FS.writeFile("/pkg.tgz", bin);
    py.runPython(\`
import tarfile, sys, os
os.makedirs('/app', exist_ok=True)
with tarfile.open('/pkg.tgz') as t:
    t.extractall('/app')
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/tools/_stubs')
os.chdir('/app')
\`);
    const res = py.runPython(\`
import io, contextlib, runpy, traceback
_buf = io.StringIO()
_code = 0
try:
    with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
        runpy.run_path('/app/${ENTRY}', run_name='__main__')
except SystemExit as e:
    _code = int(e.code or 0)
except BaseException:
    _buf.write('\\\\n' + traceback.format_exc())
    _code = 1
_buf.getvalue() + ('\\\\n__EXIT__=' + str(_code))
\`);
    show(res, res.includes("__EXIT__=0") ? "ok" : "bad");
  } catch (e) {
    show("HARNESS ERROR: " + (e && e.stack || e), "bad");
  }
  window.__ARTHA_DONE__ = true;
})();
</script></body></html>
HTMLEOF
} > "$OUT"

rm -f "$TGZ"
echo "harness → $OUT  ($(wc -c < "$OUT" | tr -d ' ') bytes, entry=$ENTRY)"

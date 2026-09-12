#!/bin/bash
# Run the real pytest suite under Pyodide.
#
# pytest is pure Python, so micropip can install it into the WebAssembly runtime.
# This machine has no interpreter, and a test suite that has never been executed
# is a document, not a test suite.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCROOT="${ARTHA_DOCROOT:?set ARTHA_DOCROOT}"
OUT="$DOCROOT/pytest.html"
PYODIDE="https://cdn.jsdelivr.net/pyodide/v314.0.6/full/"
ARGS="${1:-tests -q}"

cd "$ROOT/backend"
TGZ="$(mktemp -t artha_pkg).tgz"
COPYFILE_DISABLE=1 tar czf "$TGZ" \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='._*' \
  artha tools tests 2>/dev/null

{
  cat <<HTMLEOF
<!doctype html><html><head><meta charset="utf-8"><title>ARTHA pytest</title>
<style>body{background:#0d1117;color:#c9d1d9;font:12.5px/1.5 ui-monospace,Menlo,monospace;margin:0;padding:16px}
pre{white-space:pre-wrap;word-break:break-word}.ok{color:#3fb950}.bad{color:#f85149}.dim{color:#8b949e}</style>
</head><body><pre id="out" class="dim">booting pyodide + installing pytest…</pre>
<script src="${PYODIDE}pyodide.js"></script>
<script id="pkg" type="text/plain">
HTMLEOF
  base64 -i "$TGZ" | tr -d '\n'
  cat <<HTMLEOF

</script>
<script>
window.__PT_DONE__=false; window.__PT_OUT__="";
(async () => {
  const out = document.getElementById("out");
  const show = (s, cls) => { out.textContent = s; if (cls) out.className = cls; window.__PT_OUT__ = s; };
  try {
    const py = await loadPyodide({ indexURL: "${PYODIDE}" });
    await py.loadPackage(["numpy", "micropip"]);
    await py.runPythonAsync("import micropip\nawait micropip.install(['pytest'])");

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
import io, contextlib, traceback
_buf = io.StringIO()
_code = 0
try:
    import pytest
    with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
        _code = pytest.main("${ARGS}".split() + ['-p','no:cacheprovider','--color=no'])
except BaseException:
    _buf.write(traceback.format_exc()); _code = 1
_buf.getvalue() + ('\\\\n__EXIT__=' + str(int(_code)))
\`);
    show(res, res.includes("__EXIT__=0") ? "ok" : "bad");
  } catch (e) {
    show("HARNESS ERROR: " + (e && e.stack || e), "bad");
  }
  window.__PT_DONE__ = true;
})();
</script></body></html>
HTMLEOF
} > "$OUT"

rm -f "$TGZ"
echo "pytest page → $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes, args=$ARGS)"

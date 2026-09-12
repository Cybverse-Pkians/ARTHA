#!/bin/bash
# Syntax-check the React/TypeScript sources without a Node toolchain.
#
# There is no npm on this machine, so `tsc` cannot run. The TypeScript compiler
# is itself a browser-loadable bundle, so the sources are embedded into a page
# and transpiled there: ts.transpileModule with JSX enabled reports every syntax
# and JSX structure error, which is the class of mistake hand-written code
# actually hits. It is not a substitute for a full typecheck against @types/react
# — run `npm run typecheck` once a toolchain is available.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCROOT="${ARTHA_DOCROOT:?set ARTHA_DOCROOT}"
OUT="$DOCROOT/frontcheck.html"

{
  cat <<'HTMLEOF'
<!doctype html><html><head><meta charset="utf-8"><title>ARTHA frontend syntax check</title>
<style>body{background:#0d1117;color:#c9d1d9;font:13px/1.5 ui-monospace,Menlo,monospace;padding:16px}
pre{white-space:pre-wrap}.ok{color:#3fb950}.bad{color:#f85149}</style></head>
<body><pre id="out">loading typescript…</pre>
<script src="https://cdn.jsdelivr.net/npm/typescript@5.7.2/lib/typescript.js"></script>
<script id="src" type="application/json">
HTMLEOF

  # Emit {path: base64} for every source file.
  printf '{'
  first=1
  for f in $(cd "$ROOT" && find console/src customer-app/src -type f \( -name '*.ts' -o -name '*.tsx' \) 2>/dev/null | sort); do
    [ $first -eq 1 ] || printf ','
    first=0
    printf '"%s":"%s"' "$f" "$(base64 -i "$ROOT/$f" | tr -d '\n')"
  done
  printf '}'

  cat <<'HTMLEOF'

</script>
<script>
window.__FC_DONE__=false; window.__FC_OUT__="";
(function(){
  const out=document.getElementById('out');
  const files=JSON.parse(document.getElementById('src').textContent);
  const lines=[]; let bad=0, n=0;
  const dec=(b)=>new TextDecoder().decode(Uint8Array.from(atob(b),c=>c.charCodeAt(0)));
  for (const [path, b64] of Object.entries(files)) {
    // Declaration files emit nothing, so transpileModule has no output to make.
    if (path.endsWith(".d.ts")) { lines.push("[SKIP] " + path + "  — declaration file"); continue; }
    n++;
    const source = dec(b64);
    const isTsx = path.endsWith('.tsx');
    try {
      const res = ts.transpileModule(source, {
        fileName: path,
        reportDiagnostics: true,
        compilerOptions: {
          target: ts.ScriptTarget.ES2022,
          module: ts.ModuleKind.ESNext,
          ...(isTsx ? { jsx: ts.JsxEmit.ReactJSX } : {}),
        },
      });
      const diags = (res.diagnostics || []).filter(d => d.category === ts.DiagnosticCategory.Error);
      if (diags.length) {
        bad++;
        lines.push('[FAIL] ' + path);
        diags.slice(0,4).forEach(d => {
          const pos = d.file && d.start != null ? d.file.getLineAndCharacterOfPosition(d.start) : null;
          lines.push('        ' + (pos ? ('line ' + (pos.line+1) + ': ') : '') +
                     ts.flattenDiagnosticMessageText(d.messageText, ' '));
        });
      } else {
        lines.push('[PASS] ' + path);
      }
    } catch (e) {
      bad++;
      lines.push('[FAIL] ' + path + '  — ' + e.message);
    }
  }
  lines.push('');
  lines.push('files: ' + n + '   failed: ' + bad);
  lines.push('__EXIT__=' + (bad ? 1 : 0));
  const text = lines.join('\n');
  out.textContent = text; out.className = bad ? 'bad' : 'ok';
  window.__FC_OUT__ = text; window.__FC_DONE__ = true;
})();
</script></body></html>
HTMLEOF
} > "$OUT"

echo "frontcheck → $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes)"

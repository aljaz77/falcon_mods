// Test driver for patches/qml/FalconModsSpiral.js under Node.
//   node spiral_cli.js < request.json > result.json
// request: {"svg_paths": [{"d": "...", "transform": "..."}], "polys": [[x, y, ...]], "opts": {...}}
// result:  {"paths": [[...]], "rings": n, "length": mm, "cell": mm, "ms": t, "svg": "..."}
"use strict"
const fs = require("fs")
const path = require("path")

function load() {
    const file = path.join(__dirname, "..", "..", "patches", "qml", "FalconModsSpiral.js")
    const src = fs.readFileSync(file, "utf8").replace(/^\.pragma library\s*$/m, "")
    const mod = { exports: {} }
    new Function("module", src)(mod)      // (vm contexts run this code ~10x slower)
    return mod.exports
}

const S = load()
const req = JSON.parse(fs.readFileSync(0, "utf8"))
let polys = req.polys || []
for (const p of req.svg_paths || [])
    polys = polys.concat(S.parsePath(p.d, S.parseTransform(p.transform || ""), 0.005))
const t0 = Date.now()
const res = S.spiralFill(polys, req.opts || {})
res.ms = Date.now() - t0
res.polys = polys
if (req.svg) res.svg = S.toSvg(res.paths)
process.stdout.write(JSON.stringify(res))

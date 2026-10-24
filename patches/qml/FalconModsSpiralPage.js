// FalconMods spiral fill, page side. Runs together with FalconModsSpiral.js inside a hidden
// WebEngineView (Chromium's JS engine is ~100x faster than QML's for this, and the page can read
// the local SVG export). The patcher embeds both files as a string in FalconModsSpiralSource.js.
//
// falconModsSpiral({ url, boxes: [{x, y, width, height}], interval })
//   url:   SVG written by clApplication.saveSvg() (every shape on the canvas, in mm)
//   boxes: bounding rects of the selected shapes (canvas mm)
// returns JSON: { svg, box: [x, y, w, h], shapes, paths, length } or { error }

function falconModsSpiral(args) {
    try {
        var x = new XMLHttpRequest()
        x.open("GET", args.url, false)
        x.send()
        var doc = new DOMParser().parseFromString(x.responseText, "image/svg+xml")
        var found = readPaths(doc)
        var all = [], shapes = 0
        for (var b = 0; b < args.boxes.length; b++) {
            var group = pick(found, args.boxes[b])
            if (!group.length)
                continue
            var polys = [], nonzero = false
            group.forEach(function (g) { polys = polys.concat(g.polys); nonzero = nonzero || g.nonzero })
            var res = spiralFill(polys, { interval: args.interval, nonzero: nonzero })
            if (res.paths.length) {
                all = all.concat(res.paths)
                shapes++
            }
        }
        if (!all.length)
            return JSON.stringify({ error: shapes ? "small" : "nopath" })
        var box = bounds(all)
        return JSON.stringify({ svg: toSvg(all, box), box: box, shapes: shapes, paths: all.length,
                                length: all.reduce(function (s, p) { return s + polyLength(p) }, 0) })
    } catch (e) {
        return JSON.stringify({ error: String(e && e.stack || e) })
    }
}

// every <path> with the transforms of its ancestors applied: [{ polys, nonzero, box }]
function readPaths(doc) {
    var out = []
    var els = doc.getElementsByTagName("path")
    for (var i = 0; i < els.length; i++) {
        var m = [1, 0, 0, 1, 0, 0], chain = []
        for (var n = els[i]; n && n.getAttribute; n = n.parentNode)
            chain.unshift(n.getAttribute("transform") || "")
        chain.forEach(function (t) { m = mul(m, parseTransform(t)) })
        var polys = parsePath(els[i].getAttribute("d") || "", m, 0.005)
        if (!polys.length)
            continue
        var rule = els[i].getAttribute("fill-rule") || inherited(els[i], "fill-rule") || "nonzero"
        out.push({ polys: polys, nonzero: rule !== "evenodd", box: bounds(polys) })
    }
    return out
}

function inherited(el, name) {
    for (var n = el.parentNode; n && n.getAttribute; n = n.parentNode)
        if (n.getAttribute(name))
            return n.getAttribute(name)
    return ""
}

// paths matching a selected shape's rect; groups and text: every path inside the rect
function pick(found, r) {
    var tol = 0.05 + 0.002 * Math.max(r.width, r.height)
    function same(b) {
        return Math.abs(b[0] - r.x) < tol && Math.abs(b[1] - r.y) < tol &&
               Math.abs(b[2] - r.width) < tol && Math.abs(b[3] - r.height) < tol
    }
    function inside(b) {
        return b[0] > r.x - tol && b[1] > r.y - tol &&
               b[0] + b[2] < r.x + r.width + tol && b[1] + b[3] < r.y + r.height + tol
    }
    var exact = found.filter(function (f) { return same(f.box) })
    return exact.length ? exact : found.filter(function (f) { return inside(f.box) })
}

function bounds(paths) {
    var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity
    for (var a = 0; a < paths.length; a++)
        for (var k = 0; k < paths[a].length; k += 2) {
            minx = Math.min(minx, paths[a][k]); maxx = Math.max(maxx, paths[a][k])
            miny = Math.min(miny, paths[a][k + 1]); maxy = Math.max(maxy, paths[a][k + 1])
        }
    return [minx, miny, maxx - minx, maxy - miny]
}

.pragma library
// FalconMods spiral fill: turns a closed shape into one continuous spiral toolpath.
//
// The engine's "Offset Fill" burns concentric rings, each one a separate closed path. Here the
// rings are computed as level sets of the distance-to-outline field, and every ring N is morphed
// into ring N+1 over one turn, so the whole fill becomes one polyline (one per lobe when the
// rings split, e.g. a dumbbell or a letter with two bowls).
//
//   field:  grid of exact distances (nearest outline segment found with a Felzenszwalb EDT over
//           the cells next to the outline, then the exact point-segment distance)
//   rings:  marching squares at levels  first + k*interval, consistently oriented
//   spiral: each vertex of ring N at arc-length fraction t is projected (Newton steps on the
//           exact distance) onto level  level(N) + t*interval
//
// Runs in Qt's QML engine (V4) and in Node for the tests (tests/js/spiral_cli.js).

var BIG = 1e20

// ---------------------------------------------------------------- SVG input

function parseTransform(s) {
    var m = [1, 0, 0, 1, 0, 0]
    if (!s)
        return m
    var re = /(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)/g
    var r
    while ((r = re.exec(s)) !== null) {
        var a = r[2].split(/[\s,]+/).filter(function (x) { return x.length }).map(Number)
        var t
        if (r[1] === "matrix") t = a
        else if (r[1] === "translate") t = [1, 0, 0, 1, a[0], a.length > 1 ? a[1] : 0]
        else if (r[1] === "scale") t = [a[0], 0, 0, a.length > 1 ? a[1] : a[0], 0, 0]
        else if (r[1] === "rotate") {
            var c = Math.cos(a[0] * Math.PI / 180), sn = Math.sin(a[0] * Math.PI / 180)
            t = [c, sn, -sn, c, 0, 0]
            if (a.length > 2)
                t = mul(mul([1, 0, 0, 1, a[1], a[2]], t), [1, 0, 0, 1, -a[1], -a[2]])
        }
        else if (r[1] === "skewX") t = [1, 0, Math.tan(a[0] * Math.PI / 180), 1, 0, 0]
        else t = [1, Math.tan(a[0] * Math.PI / 180), 0, 1, 0, 0]
        m = mul(m, t)
    }
    return m
}

// a * b for SVG matrices [a b c d e f]
function mul(a, b) {
    return [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]]
}

// Path data -> list of closed polygons [x0, y0, x1, y1, ...] (curves flattened to `tol`).
// Open subpaths are closed, as a fill would. Arcs (never written by Qt's SVG generator) are
// replaced by their chord.
function parsePath(d, matrix, tol) {
    var m = matrix || [1, 0, 0, 1, 0, 0]
    tol = tol || 0.005
    var toks = d.match(/[a-zA-Z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g) || []
    var polys = [], cur = [], i = 0, cmd = "", x = 0, y = 0, sx = 0, sy = 0, cx = 0, cy = 0, prev = ""
    function num() { return Number(toks[i++]) }
    function emit(px, py) { cur.push(m[0] * px + m[2] * py + m[4], m[1] * px + m[3] * py + m[5]) }
    function flush() {
        if (cur.length >= 6)
            polys.push(cur)
        cur = []
    }
    function cubic(x1, y1, x2, y2, x3, y3) {
        var M = Math.max(Math.hypot(x - 2 * x1 + x2, y - 2 * y1 + y2), Math.hypot(x1 - 2 * x2 + x3, y1 - 2 * y2 + y3))
        var n = Math.max(1, Math.min(256, Math.ceil(Math.sqrt(0.75 * M * scaleOf(m) / tol))))
        for (var k = 1; k <= n; k++) {
            var t = k / n, u = 1 - t
            emit(u * u * u * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x3,
                 u * u * u * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y3)
        }
    }
    function quad(x1, y1, x2, y2) {
        var M = Math.hypot(x - 2 * x1 + x2, y - 2 * y1 + y2)
        var n = Math.max(1, Math.min(256, Math.ceil(Math.sqrt(0.25 * M * scaleOf(m) / tol))))
        for (var k = 1; k <= n; k++) {
            var t = k / n, u = 1 - t
            emit(u * u * x + 2 * u * t * x1 + t * t * x2, u * u * y + 2 * u * t * y1 + t * t * y2)
        }
    }
    while (i < toks.length) {
        if (/[a-zA-Z]/.test(toks[i]))
            cmd = toks[i++]
        else if (!cmd)
            { i++; continue }
        var rel = cmd === cmd.toLowerCase(), C = cmd.toUpperCase()
        var ox = rel ? x : 0, oy = rel ? y : 0
        if (C === "Z") {
            flush()
            x = sx; y = sy
            prev = C
            cmd = ""
            continue
        }
        if (i >= toks.length || /[a-zA-Z]/.test(toks[i]))
            { cmd = ""; continue }
        if (C === "M") {
            flush()
            x = ox + num(); y = oy + num(); sx = x; sy = y
            emit(x, y)
            cmd = rel ? "l" : "L"           // further pairs are line-tos
        } else if (C === "L") {
            x = ox + num(); y = oy + num(); emit(x, y)
        } else if (C === "H") {
            x = ox + num(); emit(x, y)
        } else if (C === "V") {
            y = oy + num(); emit(x, y)
        } else if (C === "C") {
            var x1 = ox + num(), y1 = oy + num(), x2 = ox + num(), y2 = oy + num(), x3 = ox + num(), y3 = oy + num()
            cubic(x1, y1, x2, y2, x3, y3); cx = x2; cy = y2; x = x3; y = y3
        } else if (C === "S") {
            var rx = (prev === "C" || prev === "S") ? 2 * x - cx : x, ry = (prev === "C" || prev === "S") ? 2 * y - cy : y
            var sx2 = ox + num(), sy2 = oy + num(), sx3 = ox + num(), sy3 = oy + num()
            cubic(rx, ry, sx2, sy2, sx3, sy3); cx = sx2; cy = sy2; x = sx3; y = sy3
        } else if (C === "Q") {
            var qx = ox + num(), qy = oy + num(), qx2 = ox + num(), qy2 = oy + num()
            quad(qx, qy, qx2, qy2); cx = qx; cy = qy; x = qx2; y = qy2
        } else if (C === "T") {
            var tx = (prev === "Q" || prev === "T") ? 2 * x - cx : x, ty = (prev === "Q" || prev === "T") ? 2 * y - cy : y
            var tx2 = ox + num(), ty2 = oy + num()
            quad(tx, ty, tx2, ty2); cx = tx; cy = ty; x = tx2; y = ty2
        } else if (C === "A") {
            i += 5
            x = ox + num(); y = oy + num(); emit(x, y)
        } else {
            i++
        }
        prev = C
    }
    flush()
    return polys
}

function scaleOf(m) {
    return Math.sqrt(Math.abs(m[0] * m[3] - m[1] * m[2])) || 1
}

// ---------------------------------------------------------------- geometry helpers

// Douglas-Peucker on an open polyline [x0, y0, ...]; returns a new array.
function simplify(p, tol) {
    var n = p.length / 2
    if (n < 3)
        return p.slice()
    var keep = new Uint8Array(n)
    keep[0] = keep[n - 1] = 1
    var stack = [0, n - 1], t2 = tol * tol
    while (stack.length) {
        var b = stack.pop(), a = stack.pop()
        var ax = p[2 * a], ay = p[2 * a + 1], dx = p[2 * b] - ax, dy = p[2 * b + 1] - ay
        var L2 = dx * dx + dy * dy, best = -1, bd = t2
        for (var k = a + 1; k < b; k++) {
            var ex = p[2 * k] - ax, ey = p[2 * k + 1] - ay, d2
            if (L2 > 0) {
                var c = ex * dy - ey * dx
                d2 = c * c / L2
                var s = (ex * dx + ey * dy) / L2
                if (s < 0) d2 = ex * ex + ey * ey
                else if (s > 1) { var fx = p[2 * k] - p[2 * b], fy = p[2 * k + 1] - p[2 * b + 1]; d2 = fx * fx + fy * fy }
            } else {
                d2 = ex * ex + ey * ey
            }
            if (d2 > bd) { bd = d2; best = k }
        }
        if (best >= 0) {
            keep[best] = 1
            stack.push(a, best, best, b)
        }
    }
    var out = []
    for (var j = 0; j < n; j++)
        if (keep[j])
            out.push(p[2 * j], p[2 * j + 1])
    return out
}

// Closed ring -> simplified closed ring (split at vertex 0 and the vertex farthest from it).
function simplifyRing(p, tol) {
    var n = p.length / 2
    if (n < 4)
        return p.slice()
    var far = 0, fd = -1
    for (var k = 1; k < n; k++) {
        var d = (p[2 * k] - p[0]) * (p[2 * k] - p[0]) + (p[2 * k + 1] - p[1]) * (p[2 * k + 1] - p[1])
        if (d > fd) { fd = d; far = k }
    }
    var a = simplify(p.slice(0, 2 * far + 2), tol)
    var b = simplify(p.slice(2 * far).concat([p[0], p[1]]), tol)
    return a.concat(b.slice(2, b.length - 2))
}

// diagonal of the bounding box
function extent(p) {
    var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity
    for (var k = 0; k < p.length; k += 2) {
        if (p[k] < minx) minx = p[k]
        if (p[k] > maxx) maxx = p[k]
        if (p[k + 1] < miny) miny = p[k + 1]
        if (p[k + 1] > maxy) maxy = p[k + 1]
    }
    return Math.hypot(maxx - minx, maxy - miny)
}

function polyLength(p) {
    var L = 0
    for (var k = 2; k < p.length; k += 2)
        L += Math.hypot(p[k] - p[k - 2], p[k + 1] - p[k - 1])
    return L
}

// ---------------------------------------------------------------- distance field

function Field(polys, opts) {
    var I = opts.interval
    var sx0 = [], sy0 = [], sx1 = [], sy1 = [], snext = [], sprev = []
    var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity
    for (var a = 0; a < polys.length; a++) {
        var p = polys[a], n = p.length / 2, first = sx0.length
        for (var k = 0; k < n; k++) {
            var x0 = p[2 * k], y0 = p[2 * k + 1], k1 = (k + 1) % n, x1 = p[2 * k1], y1 = p[2 * k1 + 1]
            if (x0 < minx) minx = x0
            if (x0 > maxx) maxx = x0
            if (y0 < miny) miny = y0
            if (y0 > maxy) maxy = y0
            if (x0 !== x1 || y0 !== y1) { sx0.push(x0); sy0.push(y0); sx1.push(x1); sy1.push(y1) }
        }
        for (var s = first; s < sx0.length; s++) {     // neighbours along the same outline
            snext.push(s + 1 < sx0.length ? s + 1 : first)
            sprev.push(s > first ? s - 1 : sx0.length - 1)
        }
    }
    this.sx0 = sx0; this.sy0 = sy0; this.sx1 = sx1; this.sy1 = sy1
    this.snext = snext; this.sprev = sprev
    this.minx = minx; this.miny = miny; this.maxx = maxx; this.maxy = maxy
    var W = maxx - minx, H = maxy - miny
    var h = Math.min(I / 2, Math.max(W, H) / 200)
    var pad = 3
    var cells = (W / h + 2 * pad + 1) * (H / h + 2 * pad + 1)
    if (cells > opts.maxCells)
        h *= Math.sqrt(cells / opts.maxCells)
    this.h = h
    this.ox = minx - pad * h
    this.oy = miny - pad * h
    this.nx = Math.ceil(W / h) + 2 * pad + 1
    this.ny = Math.ceil(H / h) + 2 * pad + 1
    this.inside = this.fill(polys, opts.nonzero)
    this.seeds()
    this.edt()
}

// inside[node]: scanline fill at node centres (even-odd or non-zero winding)
Field.prototype.fill = function (polys, nonzero) {
    var nx = this.nx, ny = this.ny, h = this.h, ox = this.ox, oy = this.oy
    var inside = new Uint8Array(nx * ny)
    var rows = new Array(ny)
    for (var j = 0; j < ny; j++) rows[j] = []
    for (var s = 0; s < this.sx0.length; s++) {
        var x0 = this.sx0[s], y0 = this.sy0[s], x1 = this.sx1[s], y1 = this.sy1[s]
        if (y0 === y1) continue
        var dir = y1 > y0 ? 1 : -1
        var ya = Math.min(y0, y1), yb = Math.max(y0, y1)
        var j0 = Math.max(0, Math.ceil((ya - oy) / h)), j1 = Math.min(ny - 1, Math.ceil((yb - oy) / h) - 1)
        for (var jj = j0; jj <= j1; jj++) {
            var y = oy + jj * h          // half-open [ya, yb)
            if (y < ya || y >= yb) continue
            rows[jj].push(x0 + (y - y0) * (x1 - x0) / (y1 - y0), dir)
        }
    }
    for (j = 0; j < ny; j++) {
        var r = rows[j], m = r.length / 2
        if (!m) continue
        var idx = []
        for (var q = 0; q < m; q++) idx.push(q)
        idx.sort(function (a, b) { return r[2 * a] - r[2 * b] })
        var w = 0
        for (q = 0; q < m - 1; q++) {
            w += r[2 * idx[q] + 1]
            var on = nonzero ? w !== 0 : (q & 1) === 0
            if (!on) continue
            var i0 = Math.max(0, Math.ceil((r[2 * idx[q]] - ox) / h)), i1 = Math.min(nx - 1, Math.floor((r[2 * idx[q + 1]] - ox) / h))
            for (var i = i0; i <= i1; i++) inside[j * nx + i] = 1
        }
    }
    return inside
}

// Nodes within ~2 cells of the outline get their exact nearest segment.
Field.prototype.seeds = function () {
    var nx = this.nx, ny = this.ny, h = this.h, ox = this.ox, oy = this.oy
    var seg = new Int32Array(nx * ny).fill(-1)
    var sd = new Float64Array(nx * ny).fill(BIG)
    for (var s = 0; s < this.sx0.length; s++) {
        var x0 = this.sx0[s], y0 = this.sy0[s], dx = this.sx1[s] - x0, dy = this.sy1[s] - y0
        var L2 = dx * dx + dy * dy, n = Math.ceil(Math.sqrt(L2) / h) + 1
        for (var t = 0; t <= n; t++) {
            var ci = Math.round((x0 + dx * t / n - ox) / h), cj = Math.round((y0 + dy * t / n - oy) / h)
            for (var j = cj - 2; j <= cj + 2; j++) {
                if (j < 0 || j >= ny) continue
                for (var i = ci - 2; i <= ci + 2; i++) {
                    if (i < 0 || i >= nx) continue
                    var px = ox + i * h - x0, py = oy + j * h - y0
                    var u = Math.max(0, Math.min(1, (px * dx + py * dy) / L2))
                    var ex = px - u * dx, ey = py - u * dy, d2 = ex * ex + ey * ey
                    var id = j * nx + i
                    if (d2 < sd[id]) { sd[id] = d2; seg[id] = s }
                }
            }
        }
    }
    this.seedSeg = seg
}

function edt1(f, n, out, arg, v, z) {
    var k = -1
    for (var q = 0; q < n; q++) {
        if (f[q] >= BIG) continue
        var s = 0
        while (k >= 0) {
            var p = v[k]
            s = ((f[q] + q * q) - (f[p] + p * p)) / (2 * q - 2 * p)
            if (s <= z[k]) k--
            else break
        }
        k++
        v[k] = q
        z[k] = k === 0 ? -Infinity : s
        z[k + 1] = Infinity
    }
    if (k < 0) {
        for (q = 0; q < n; q++) { out[q] = BIG; arg[q] = -1 }
        return
    }
    var kk = 0
    for (q = 0; q < n; q++) {
        while (z[kk + 1] < q) kk++
        var pp = v[kk]
        out[q] = (q - pp) * (q - pp) + f[pp]
        arg[q] = pp
    }
}

// Nearest seed for every node (Felzenszwalb & Huttenlocher), then its exact segment distance.
Field.prototype.edt = function () {
    var nx = this.nx, ny = this.ny, N = nx * ny, seed = this.seedSeg
    var m = Math.max(nx, ny)
    var f = new Float64Array(m), out = new Float64Array(m), arg = new Int32Array(m)
    var v = new Int32Array(m), z = new Float64Array(m + 1)
    var g = new Float64Array(N), argJ = new Int32Array(N)
    for (var i = 0; i < nx; i++) {
        for (var j = 0; j < ny; j++) f[j] = seed[j * nx + i] >= 0 ? 0 : BIG
        edt1(f, ny, out, arg, v, z)
        for (j = 0; j < ny; j++) { g[j * nx + i] = out[j]; argJ[j * nx + i] = arg[j] }
    }
    var nseg = new Int32Array(N), val = new Float64Array(N)
    var dmax = 0
    for (j = 0; j < ny; j++) {
        for (i = 0; i < nx; i++) f[i] = g[j * nx + i]
        edt1(f, nx, out, arg, v, z)
        for (i = 0; i < nx; i++) {
            var id = j * nx + i, si = arg[i]
            var s = si < 0 ? -1 : seed[argJ[j * nx + si] * nx + si]
            var x = this.ox + i * this.h, y = this.oy + j * this.h
            if (s >= 0) s = this.descend(s, x, y)
            nseg[id] = s
            var d = s < 0 ? BIG : this.segDist(s, x, y)
            val[id] = this.inside[id] ? d : -d
            if (this.inside[id] && d > dmax) dmax = d
        }
    }
    this.nseg = nseg
    this.val = val
    this.dmax = dmax
}

Field.prototype.segDist = function (s, x, y) {
    var x0 = this.sx0[s], y0 = this.sy0[s], dx = this.sx1[s] - x0, dy = this.sy1[s] - y0
    var px = x - x0, py = y - y0, L2 = dx * dx + dy * dy
    var u = L2 > 0 ? Math.max(0, Math.min(1, (px * dx + py * dy) / L2)) : 0
    return Math.hypot(px - u * dx, py - u * dy)
}

// The seed's segment is only nearly the nearest one (flattened curves have many short
// segments); walk along the outline while the distance keeps dropping.
Field.prototype.descend = function (s, x, y) {
    var d = this.segDist(s, x, y)
    for (var dir = 0; dir < 2; dir++) {
        var link = dir ? this.sprev : this.snext
        for (var it = 0; it < 256; it++) {
            var t = link[s], dt = this.segDist(t, x, y)
            if (dt >= d) break
            s = t
            d = dt
        }
    }
    return s
}

// Exact unsigned distance at (x, y) and its gradient (pointing away from the outline).
Field.prototype.probe = function (x, y, res) {
    var h = this.h, nx = this.nx
    var i = Math.floor((x - this.ox) / h), j = Math.floor((y - this.oy) / h)
    i = Math.max(0, Math.min(this.nx - 2, i))
    j = Math.max(0, Math.min(this.ny - 2, j))
    var best = BIG, bx = 0, by = 0, tried0 = -2, tried1 = -2, tried2 = -2
    for (var c = 0; c < 4; c++) {
        var s = this.nseg[(j + (c >> 1)) * nx + i + (c & 1)]
        if (s < 0 || s === tried0 || s === tried1 || s === tried2) continue
        if (c === 0) tried0 = s
        else if (c === 1) tried1 = s
        else tried2 = s
        s = this.descend(s, x, y)
        var x0 = this.sx0[s], y0 = this.sy0[s], dx = this.sx1[s] - x0, dy = this.sy1[s] - y0
        var px = x - x0, py = y - y0, L2 = dx * dx + dy * dy
        var u = L2 > 0 ? Math.max(0, Math.min(1, (px * dx + py * dy) / L2)) : 0
        var ex = px - u * dx, ey = py - u * dy, d = Math.hypot(ex, ey)
        if (d < best) { best = d; bx = ex; by = ey }
    }
    res.d = best
    res.gx = best > 0 ? bx / best : 0
    res.gy = best > 0 ? by / best : 0
    return res
}

// Move pt onto the level `L` along the distance gradient, by at most `maxMove`. Returns false
// (pt unchanged) if it doesn't get there: the level doesn't exist nearby, e.g. past the tip of a
// vanishing ring, or the steps run across a ridge of the field towards another part of the shape.
Field.prototype.project = function (pt, L, tol, maxMove) {
    var r = {}, x = pt[0], y = pt[1], ok = false
    for (var it = 0; it < 8 && !ok; it++) {
        this.probe(x, y, r)
        var e = L - r.d
        if (Math.abs(e) < tol) { ok = true; break }
        x += e * r.gx
        y += e * r.gy
    }
    if (!ok) {
        this.probe(x, y, r)
        ok = Math.abs(L - r.d) < 20 * tol
    }
    if (!ok || Math.hypot(x - pt[0], y - pt[1]) > maxMove)
        return false
    pt[0] = x; pt[1] = y
    return true
}

// ---------------------------------------------------------------- rings (marching squares)

Field.prototype.rings = function (opts) {
    var I = opts.interval, l0 = opts.first, nx = this.nx, ny = this.ny, val = this.val, h = this.h
    var K = this.dmax > l0 ? Math.floor((this.dmax - l0) / I) + 1 : 0
    var levels = []
    if (!K)
        return levels
    // bucket cells by the levels that cross them
    var count = new Int32Array(K + 1)
    var pass, i, j, id
    var list = null
    for (pass = 0; pass < 2; pass++) {
        for (j = 0; j < ny - 1; j++) {
            for (i = 0; i < nx - 1; i++) {
                id = j * nx + i
                var a = val[id], b = val[id + 1], c = val[id + nx + 1], d = val[id + nx]
                var vmax = Math.max(a, b, c, d)
                if (vmax <= l0) continue
                var vmin = Math.min(a, b, c, d)
                // one extra level either side, then the exact test used by trace() (a node value
                // can equal a level exactly, e.g. on axis-aligned shapes)
                var k0 = Math.max(0, Math.ceil((vmin - l0) / I) - 1), k1 = Math.min(K - 1, Math.ceil((vmax - l0) / I))
                for (var k = k0; k <= k1; k++) {
                    var Lk = l0 + k * I
                    if (!(vmin <= Lk && Lk < vmax)) continue
                    if (pass === 0) count[k + 1]++
                    else list[count[k]++] = id
                }
            }
        }
        if (pass === 0) {
            for (k = 1; k <= K; k++) count[k] += count[k - 1]
            list = new Int32Array(count[K])         // count[k] = start of bucket k
        }
    }
    // after pass 2, count[k] is the end of bucket k and the start of bucket k+1
    var markLevel = new Int32Array(nx * ny).fill(-1), markComp = new Int32Array(nx * ny)
    var start = 0
    var simplifyTol = opts.tolerance
    var pt = [0, 0]
    for (k = 0; k < K; k++) {
        var L = l0 + k * I
        var loops = this.trace(list, start, count[k], L)
        start = count[k]
        var comps = []
        for (var q = 0; q < loops.length; q++) {
            var ring = loops[q]
            for (var v = 0; v < ring.length; v += 2) {      // polish onto the exact level
                pt[0] = ring[v]; pt[1] = ring[v + 1]
                if (this.project(pt, L, 1e-5, h)) { ring[v] = pt[0]; ring[v + 1] = pt[1] }
            }
            ring = simplifyRing(ring, simplifyTol)
            // Specks smaller than one interval (flat tops of the distance field) are already
            // covered by the ring around them and would only add laser jumps.
            if (ring.length < 6 || extent(ring) < I) continue
            comps.push({ level: k, pts: ring, parent: null, children: [] })
        }
        // parent = the ring of the previous level found one interval further out
        if (k > 0) {
            var r = {}
            for (q = 0; q < comps.length; q++) {
                var c0 = comps[q], px = c0.pts[0], py = c0.pts[1]
                this.probe(px, py, r)
                var qx = px - I * r.gx, qy = py - I * r.gy
                var ci = Math.floor((qx - this.ox) / h), cj = Math.floor((qy - this.oy) / h)
                var best = -1, bd = Infinity, R = Math.ceil(I / h) + 2
                for (var dj = -R; dj <= R; dj++) {
                    for (var di = -R; di <= R; di++) {
                        var ii = ci + di, jj = cj + dj
                        if (ii < 0 || jj < 0 || ii >= nx || jj >= ny) continue
                        var cid = jj * nx + ii
                        if (markLevel[cid] !== k - 1) continue
                        var dd = di * di + dj * dj
                        if (dd < bd) { bd = dd; best = markComp[cid] }
                    }
                }
                if (best >= 0) {
                    c0.parent = levels[k - 1][best]
                    c0.parent.children.push(c0)
                }
            }
        }
        for (q = 0; q < comps.length; q++) {
            var pp = comps[q].pts, np = pp.length / 2
            for (v = 0; v < np; v++) {               // walk every segment in steps of h
                var v1 = (v + 1) % np, ax = pp[2 * v], ay = pp[2 * v + 1]
                var sdx = pp[2 * v1] - ax, sdy = pp[2 * v1 + 1] - ay
                var steps = Math.ceil(Math.hypot(sdx, sdy) / h) + 1
                for (var st = 0; st < steps; st++) {
                    var mi = Math.floor((ax + sdx * st / steps - this.ox) / h)
                    var mj = Math.floor((ay + sdy * st / steps - this.oy) / h)
                    if (mi < 0 || mj < 0 || mi >= nx || mj >= ny) continue
                    markLevel[mj * nx + mi] = k
                    markComp[mj * nx + mi] = q
                }
            }
        }
        levels.push(comps)
    }
    return levels
}

// Oriented iso-lines at level L through the cells list[from..to). Every crossing is an "exit"
// (inside -> outside, walking the cell clockwise) in one cell and an "enter" in its neighbour, so
// segments exit->enter chain up into closed, consistently oriented loops.
Field.prototype.trace = function (list, from, to, L) {
    var nx = this.nx, val = this.val, h = this.h, ox = this.ox, oy = this.oy
    var next = new Map(), pos = new Map()
    var ce = [0, 0, 0, 0], ct = [0, 0, 0, 0]
    for (var n = from; n < to; n++) {
        var id = list[n], i = id % nx, j = (id - i) / nx
        var na = id, nb = id + 1, nc = id + nx + 1, nd = id + nx
        var cnt = 0
        // edges in clockwise order: top a->b, right b->c, bottom c->d, left d->a
        var nodes0 = [na, nb, nc, nd], nodes1 = [nb, nc, nd, na]
        var eids = [2 * na, 2 * nb + 1, 2 * nd, 2 * na + 1]
        for (var e = 0; e < 4; e++) {
            var v0 = val[nodes0[e]], v1 = val[nodes1[e]]
            var in0 = v0 > L, in1 = v1 > L
            if (in0 === in1) continue
            var eid = eids[e]
            if (!pos.has(eid)) {
                var t = (L - v0) / (v1 - v0)
                var p0 = nodes0[e], p1 = nodes1[e]
                var x0 = ox + (p0 % nx) * h, y0 = oy + Math.floor(p0 / nx) * h
                var x1 = ox + (p1 % nx) * h, y1 = oy + Math.floor(p1 / nx) * h
                pos.set(eid, [x0 + t * (x1 - x0), y0 + t * (y1 - y0)])
            }
            ce[cnt] = eid
            ct[cnt] = in0 ? 1 : 0          // 1 = exit
            cnt++
        }
        if (cnt === 2) {
            if (ct[0]) next.set(ce[0], ce[1])
            else next.set(ce[1], ce[0])
        } else if (cnt === 4) {
            var centre = (val[na] + val[nb] + val[nc] + val[nd]) / 4 > L
            for (var q = 0; q < 4; q++) {
                if (!ct[q]) continue
                // inside connected through the centre: pair with the next enter, else the previous
                next.set(ce[q], ce[(q + (centre ? 1 : 3)) % 4])
            }
        }
    }
    var loops = [], seen = new Set()
    next.forEach(function (_, s) {
        if (seen.has(s)) return
        var ring = [], e = s
        while (e !== undefined && !seen.has(e)) {
            seen.add(e)
            var p = pos.get(e)
            ring.push(p[0], p[1])
            e = next.get(e)
        }
        if (e === s && ring.length >= 6)          // only closed loops (always, given complete cells)
            loops.push(ring)
    })
    return loops
}

// ---------------------------------------------------------------- spiral

// Rotate closed ring `r` to start at the point of r nearest to (x, y) (inserted if needed).
function rotateTo(r, x, y) {
    var n = r.length / 2, best = 0, bd = Infinity, bx = r[0], by = r[1]
    for (var k = 0; k < n; k++) {
        var k1 = (k + 1) % n
        var x0 = r[2 * k], y0 = r[2 * k + 1], dx = r[2 * k1] - x0, dy = r[2 * k1 + 1] - y0
        var L2 = dx * dx + dy * dy
        var u = L2 > 0 ? Math.max(0, Math.min(1, ((x - x0) * dx + (y - y0) * dy) / L2)) : 0
        var px = x0 + u * dx, py = y0 + u * dy, d = (px - x) * (px - x) + (py - y) * (py - y)
        if (d < bd) { bd = d; best = k; bx = px; by = py }
    }
    var out = [bx, by]
    for (k = 1; k <= n; k++) {
        var m = (best + k) % n
        out.push(r[2 * m], r[2 * m + 1])
    }
    // drop a duplicate if the projection hit a vertex
    if (Math.hypot(out[2] - bx, out[3] - by) < 1e-9) out.splice(2, 2)
    if (Math.hypot(out[out.length - 2] - bx, out[out.length - 1] - by) < 1e-9) out.splice(out.length - 2, 2)
    return out
}

// One turn: walk ring r (starting at its first point and closing back to it) while the target
// level rises linearly from L0 to L1. Returns the points; the last one lies on level L1.
// Where the deeper level doesn't exist (a tongue of ring r that ends before the next ring), the
// point stays as deep as it can get, down to r itself, so the tongue is still burned.
function turn(field, r, L0, L1, tol) {
    var closed = r.concat([r[0], r[1]])
    var n = closed.length / 2, total = polyLength(closed)
    var out = [], acc = 0, pt = [0, 0], fr = [1, 0.75, 0.5, 0.25]
    for (var k = 0; k < n; k++) {
        if (k > 0) acc += Math.hypot(closed[2 * k] - closed[2 * k - 2], closed[2 * k + 1] - closed[2 * k - 1])
        var x = closed[2 * k], y = closed[2 * k + 1], rise = (L1 - L0) * acc / total
        var ok = false
        for (var f = 0; f < fr.length && !ok; f++) {
            pt[0] = x; pt[1] = y
            // must converge on this side of the ridge, about `rise` away along the gradient
            ok = field.project(pt, L0 + rise * fr[f], tol, 1.5 * rise * fr[f] + field.h)
        }
        out.push(pt[0], pt[1])
    }
    return out
}

function appendPts(dst, src, from) {
    for (var k = from || 0; k < src.length; k++) dst.push(src[k])
}

// polys: closed polygons [x0, y0, x1, y1, ...] in mm (even-odd unless opts.nonzero)
// opts: interval (mm), first (offset of the first ring, default interval/2), nonzero (fill rule),
//       tolerance (simplification, mm), maxCells (grid size limit)
// Returns { paths: [[x0, y0, ...], ...], rings, length, cell }
function spiralFill(polys, opts) {
    opts = opts || {}
    var o = {
        interval: opts.interval || 0.2,
        first: opts.first !== undefined && opts.first >= 0 ? opts.first : (opts.interval || 0.2) / 2,
        nonzero: !!opts.nonzero,
        tolerance: opts.tolerance || Math.min(0.005, (opts.interval || 0.2) / 20),
        maxCells: opts.maxCells || 4000000
    }
    var res = { paths: [], rings: 0, length: 0, cell: 0 }
    polys = polys.filter(function (p) { return p.length >= 6 })
    if (!polys.length)
        return res
    var field = new Field(polys, o)
    res.cell = field.h
    var levels = field.rings(o)
    var I = o.interval, tol = Math.min(1e-4, o.tolerance / 10)
    var starts = []
    for (var k = 0; k < levels.length; k++) {
        res.rings += levels[k].length
        for (var q = 0; q < levels[k].length; q++) {
            var c = levels[k][q]
            if (!c.parent || c.parent.children.length > 1)
                starts.push(c)
        }
    }
    for (var s = 0; s < starts.length; s++) {
        var c0 = starts[s]
        var chain = [c0]
        while (chain[chain.length - 1].children.length === 1)
            chain.push(chain[chain.length - 1].children[0])
        // start at the top-left-most point of the first ring
        var r = c0.pts, bi = 0
        for (var v = 2; v < r.length; v += 2)
            if (r[v] + r[v + 1] < r[bi] + r[bi + 1]) bi = v
        r = rotateTo(r, r[bi], r[bi + 1])
        // A full loop of the first ring keeps the spacing to the outline (or to the last loop of
        // the parent chain) at one interval; the turns then step one interval per revolution.
        var path = r.slice()
        path.push(r[0], r[1])
        for (var m = 0; m + 1 < chain.length; m++) {
            var L0 = o.first + chain[m].level * I
            var tp = turn(field, r, L0, L0 + I, tol)
            appendPts(path, tp, 2)
            r = rotateTo(chain[m + 1].pts, tp[tp.length - 2], tp[tp.length - 1])
        }
        var last = chain[chain.length - 1], Ll = o.first + last.level * I
        if (!last.children.length) {
            // innermost ring: one more turn reaches as deep as the shape allows (the centre)
            appendPts(path, turn(field, r, Ll, Ll + I, tol), 2)
        } else if (chain.length > 1) {
            // the rings split here: close with a full loop, each branch starts its own spiral
            appendPts(path, r, 2)
            path.push(r[0], r[1])
        }
        path = simplify(path, o.tolerance)
        res.length += polyLength(path)
        res.paths.push(path)
    }
    return res
}

// ---------------------------------------------------------------- SVG output

function fmt(v) {
    return (Math.round(v * 10000) / 10000).toString()
}

// paths in mm -> SVG document in mm. `box` = [x, y, w, h] of the viewBox (default: paths' bounds).
function toSvg(paths, box) {
    if (!box) {
        var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity
        for (var a = 0; a < paths.length; a++)
            for (var k = 0; k < paths[a].length; k += 2) {
                minx = Math.min(minx, paths[a][k]); maxx = Math.max(maxx, paths[a][k])
                miny = Math.min(miny, paths[a][k + 1]); maxy = Math.max(maxy, paths[a][k + 1])
            }
        box = [minx, miny, maxx - minx, maxy - miny]
    }
    var out = ['<?xml version="1.0" encoding="UTF-8"?>\n',
               '<svg xmlns="http://www.w3.org/2000/svg" width="', fmt(box[2]), 'mm" height="', fmt(box[3]),
               'mm" viewBox="', fmt(box[0]), ' ', fmt(box[1]), ' ', fmt(box[2]), ' ', fmt(box[3]), '">\n']
    for (a = 0; a < paths.length; a++) {
        var p = paths[a], d = ["M", fmt(p[0]), ",", fmt(p[1])]
        for (k = 2; k < p.length; k += 2)
            d.push(k === 2 ? " L" : " ", fmt(p[k]), ",", fmt(p[k + 1]))
        out.push('<path fill="none" stroke="#000000" stroke-width="0.1" d="', d.join(""), '"/>\n')
    }
    out.push('</svg>\n')
    return out.join("")
}

if (typeof module !== "undefined")
    module.exports = { parsePath: parsePath, parseTransform: parseTransform, spiralFill: spiralFill,
                       toSvg: toSvg, simplify: simplify, polyLength: polyLength }

// Pixel-art bison. Every frame is rasterised from a posed skeleton into a small
// buffer (shapes -> shading -> outlines), then scaled up with crisp pixels.
// Bison.mount(canvas, {mood, action, gear}) starts the loop and returns {set}.
(() => {
  const W = 96, H = 80, G = 76;          // buffer size, ground line
  const X0 = 36;                          // where he stands

  const hex = (h) => {
    const n = parseInt(h.slice(1), 16);
    return (0xff << 24 | (n & 0xff) << 16 | (n >> 8 & 0xff) << 8 | n >> 16) >>> 0;
  };
  const ramp = (hi, base, sh) => ({ hi: hex(hi), base: hex(base), sh: hex(sh) });
  // Bison: shaggy dark wool on the hump, head and upper arms, shorter rusty hide
  // behind. Black shorts; bracers and hooves come from Jeff's original sprite.
  const C = {
    fur: ramp("#c08450", "#8e5c36", "#5a3820"),       // hide
    furBack: ramp("#8a5c38", "#6a4428", "#42281a"),
    wool: ramp("#a8784a", "#6e4828", "#3c2414"),
    woolBack: ramp("#7a5232", "#4e321c", "#2c1a0e"),
    woolTip: ramp("#c89a64", "#93683e", "#5a3c22"),
    muzzle: ramp("#9a7a66", "#64493c", "#382820"),
    red: ramp("#e0402a", "#b01800", "#781000"),
    horn: ramp("#c8c8d0", "#5a5a62", "#2a2a2e"),
    gold: ramp("#fff0a0", "#e8c040", "#b08a20"),
    belly: ramp("#d09a60", "#a87044", "#7a4e2c"),
    blue: ramp("#9ad8ff", "#2f8ae0", "#1a4f96"),
    shorts: ramp("#55555c", "#26262a", "#121214"),
    shortsBack: ramp("#3a3a40", "#1a1a1d", "#0c0c0e"),
    grey: ramp("#d0d0d0", "#888888", "#555555"),
    hoof: ramp("#5a5a5a", "#303030", "#1a1a1a"),
    volt: ramp("#f6ffb0", "#e8ff3a", "#a8bb10"),
    ball: ramp("#6a6a78", "#3a3a44", "#202026"),
    metal: ramp("#9a9aa6", "#5c5c66", "#34343c"),
    white: ramp("#ffffff", "#f8f8f8", "#c8c8c8"),
    sweat: ramp("#e0f4ff", "#8fd3ff", "#4a9ad0"),
  };
  const OUTLINE = hex("#0d0805"), INNER = hex("#2a170c");
  const EYE = hex("#f8e050"), PUPIL = hex("#0d0805"), LID = hex("#684028"), MOUTH = hex("#3a0c06");
  const SHADOW = (0x50 << 24) >>> 0;     // translucent black
  const STEAM = hex("#e8e8e8"), DUST = hex("#8a7a66"), VOLT = hex("#e8ff3a"), WHITE = hex("#ffffff");
  const L = [-0.55, -0.83];               // light from the top left

  // ---------- raster buffer ----------

  const col = new Uint32Array(W * H), lay = new Int16Array(W * H), grp = new Int16Array(W * H);
  let layer = 0;
  const GROUPS = {};
  const gid = (name) => (GROUPS[name] ||= Object.keys(GROUPS).length + 1);

  function clear() { col.fill(0); lay.fill(0); grp.fill(0); layer = 0; }

  function shade(r, nx, ny, r2) {
    const l = nx * L[0] + ny * L[1];
    if (r2 > 0.55 && l > 0.6) return r.hi;
    if (r2 > 0.3 && l < -0.2) return r.sh;
    return r.base;
  }

  function plot(x, y, c, g) {
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    const i = y * W + x;
    col[i] = c; lay[i] = layer; grp[i] = g;
  }

  function ellipse(cx, cy, rx, ry, rot, r, group) {
    layer++;
    const g = gid(group), cs = Math.cos(rot), sn = Math.sin(rot), m = Math.max(rx, ry) + 1;
    for (let y = Math.floor(cy - m); y <= cy + m; y++) {
      for (let x = Math.floor(cx - m); x <= cx + m; x++) {
        const dx = x + 0.5 - cx, dy = y + 0.5 - cy;
        const u = (dx * cs + dy * sn) / rx, v = (-dx * sn + dy * cs) / ry;
        const r2 = u * u + v * v;
        if (r2 > 1) continue;
        plot(x, y, shade(r, u * cs - v * sn, u * sn + v * cs, r2), g);
      }
    }
  }

  function capsule(a, b, ra, rb, r, group) {
    layer++;
    const g = gid(group), dx = b[0] - a[0], dy = b[1] - a[1], len2 = dx * dx + dy * dy || 1e-6;
    const m = Math.max(ra, rb) + 1;
    for (let y = Math.floor(Math.min(a[1], b[1]) - m); y <= Math.max(a[1], b[1]) + m; y++) {
      for (let x = Math.floor(Math.min(a[0], b[0]) - m); x <= Math.max(a[0], b[0]) + m; x++) {
        const px = x + 0.5, py = y + 0.5;
        const t = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / len2));
        const rad = ra + (rb - ra) * t;
        const nx = (px - a[0] - dx * t) / rad, ny = (py - a[1] - dy * t) / rad;
        const r2 = nx * nx + ny * ny;
        if (r2 > 1) continue;
        plot(x, y, shade(r, nx, ny, r2), g);
      }
    }
  }

  function poly(pts, c, group) {
    layer++;
    const g = gid(group);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    for (let y = Math.floor(Math.min(...ys)); y <= Math.max(...ys); y++) {
      for (let x = Math.floor(Math.min(...xs)); x <= Math.max(...xs); x++) {
        const px = x + 0.5, py = y + 0.5;
        let inside = false;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
          const [xi, yi] = pts[i], [xj, yj] = pts[j];
          if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
        }
        if (inside) plot(x, y, c, g);
      }
    }
  }

  function glyph(rows, x, y, c, group) {
    layer++;
    const g = gid(group);
    rows.forEach((row, j) => [...row].forEach((ch, i) => { if (ch === "#") plot(Math.round(x) + i, Math.round(y) + j, c, g); }));
  }

  // Outer outline on empty pixels next to the sprite, inner lines where a part
  // sits in front of a different part.
  function outline() {
    const out = new Uint32Array(col);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = y * W + x;
        const nb = [x > 0 ? i - 1 : -1, x < W - 1 ? i + 1 : -1, y > 0 ? i - W : -1, y < H - 1 ? i + W : -1];
        if (!col[i]) {
          if (nb.some((j) => j >= 0 && col[j])) out[i] = OUTLINE;
        } else if (nb.some((j) => j >= 0 && col[j] && grp[j] !== grp[i] && lay[j] > lay[i])) {
          out[i] = INNER;
        }
      }
    }
    col.set(out);
  }

  const px = (x, y, c) => { x = Math.round(x); y = Math.round(y); if (x >= 0 && y >= 0 && x < W && y < H) col[y * W + x] = c; };
  const pxEmpty = (x, y, c) => { x = Math.round(x); y = Math.round(y); if (x >= 0 && y >= 0 && x < W && y < H && !col[y * W + x]) col[y * W + x] = c; };

  // ---------- geometry ----------

  const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
  const mul = (a, k) => [a[0] * k, a[1] * k];
  const lerp = (a, b, t) => a + (b - a) * t;
  const lerp2 = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t)];
  const rot = (v, ang) => [v[0] * Math.cos(ang) - v[1] * Math.sin(ang), v[0] * Math.sin(ang) + v[1] * Math.cos(ang)];
  const ease = (t) => t * t * (3 - 2 * t);
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

  // Two-bone IK: the middle joint bends towards `pole`.
  function ik(root, target, l1, l2, pole) {
    let dx = target[0] - root[0], dy = target[1] - root[1];
    let d = Math.hypot(dx, dy) || 1e-6;
    const dmax = l1 + l2 - 0.01;
    if (d > dmax) { dx *= dmax / d; dy *= dmax / d; d = dmax; }
    const end = [root[0] + dx, root[1] + dy];
    const a = Math.acos(clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1, 1));
    const base = Math.atan2(dy, dx);
    const c1 = [root[0] + l1 * Math.cos(base + a), root[1] + l1 * Math.sin(base + a)];
    const c2 = [root[0] + l1 * Math.cos(base - a), root[1] + l1 * Math.sin(base - a)];
    const mid = [(root[0] + end[0]) / 2, (root[1] + end[1]) / 2];
    const s = (c) => (c[0] - mid[0]) * pole[0] + (c[1] - mid[1]) * pole[1];
    return [s(c1) >= s(c2) ? c1 : c2, end];
  }

  // Keyframes: [[p, {params}], ...] -> params interpolated at p (0..1).
  function kf(frames, p) {
    let i = 0;
    while (i < frames.length - 2 && p > frames[i + 1][0]) i++;
    const [p0, a] = frames[i], [p1, b] = frames[i + 1];
    const t = ease(clamp((p - p0) / (p1 - p0 || 1), 0, 1));
    const out = {};
    for (const k in a) out[k] = Array.isArray(a[k]) ? lerp2(a[k], b[k], t) : typeof a[k] === "number" ? lerp(a[k], b[k], t) : a[k];
    return out;
  }

  // ---------- the bison ----------

  const ARM = [8.5, 8], LEG = [9, 8.5];
  const GROUND = G - 2;                    // ankle height when standing

  function skeleton(p) {
    const u = [Math.sin(p.lean), -Math.cos(p.lean)];
    const hip = p.hip;
    const S = add(hip, mul(u, 20));
    const sk = { hip, u, lean: p.lean };
    sk.shF = add(S, rot([-2, 2], p.lean));
    sk.shB = add(S, rot([3, -1], p.lean));
    sk.hipF = add(hip, [1, 1]);
    sk.hipB = add(hip, [-2, 0]);
    [sk.elF, sk.haF] = ik(sk.shF, p.handF, ARM[0], ARM[1], p.elbowF || [-1, 0.6]);
    [sk.elB, sk.haB] = ik(sk.shB, p.handB, ARM[0], ARM[1], p.elbowB || [-1, 0.6]);
    [sk.knF, sk.ftF] = ik(sk.hipF, p.footF, LEG[0], LEG[1], p.kneeF || [1, -0.2]);
    [sk.knB, sk.ftB] = ik(sk.hipB, p.footB, LEG[0], LEG[1], p.kneeB || [1, -0.2]);
    sk.neck = add(hip, mul(u, 19));
    sk.headAng = p.lean * 0.6 + (p.tilt || 0);
    sk.head = add(add(hip, mul(u, 21)), rot([9, -4], sk.headAng));
    return sk;
  }

  function leg(hp, kn, ft, fur, side) {
    capsule(hp, kn, 5.2, 4, fur, "leg" + side);
    capsule(hp, lerp2(hp, kn, 0.55), 5.8, 5, side === "F" ? C.shorts : C.shortsBack, "shorts" + side);
    capsule(kn, ft, 3.8, 2.8, fur, "leg" + side);
    ellipse(ft[0] + 1.5, ft[1] + 0.6, 3.2, 2, 0, C.hoof, "hoof" + side);
  }

  function arm(sh, el, ha, fur, side, gear, flex) {
    const wool = side === "F" ? C.wool : C.woolBack;
    capsule(sh, el, 4.8, 3.8, wool, "arm" + side);
    if (flex) ellipse(...add(lerp2(sh, el, 0.5), [0, -2.5 - flex]), 3.5 + flex * 0.4, 2.4 + flex, 0, wool, "arm" + side);
    capsule(el, ha, 3.8, 3.2, fur, "arm" + side);
    capsule(lerp2(el, ha, 0.35), lerp2(el, ha, 0.7), 4.1, 3.7, C.grey, "bracer" + side);
    if (gear.wraps) capsule(lerp2(el, ha, 0.82), lerp2(el, ha, 0.95), 3.5, 3.4, C.volt, "wrap" + side);
    ellipse(ha[0], ha[1], 3.4, 3.2, 0, fur, "arm" + side);
  }

  function head(sk, p, gear) {
    const h = sk.head, A = sk.headAng, at = (v) => add(h, rot(v, A));
    const bounce = p.maneBounce || 0;
    // short hooked horns: the far one sits behind the head
    hornChain([at([-2, -3]), at([-6, -4.5]), at([-7.5, -8]), at([-6, -10.5])], "hornB");
    ellipse(...at([-6, 0]), 3, 1.8, A - 0.5, C.woolBack, "ear");
    // shaggy skull, broad short face, dark muzzle
    ellipse(h[0], h[1], 7.5, 7, A, C.wool, "head");
    capsule(at([3.5, 1.5]), at([9.5, 3.5]), 4.8, 4.2, C.muzzle, "face");
    ellipse(...at([10.5, 3.7]), 3, 2.8, A + 0.2, C.muzzle, "face");
    // beard hanging under the chin
    const sway = Math.sin(p.t * 5) * bounce * 0.8;
    poly([at([-1, 5]), at([8, 7]), at([6 + sway, 11]), at([3.5 + sway, 16]), at([1 + sway, 11])], C.woolTip.base, "beard");
    // woolly topknot
    [[-4, -5.5, 3.5], [-1, -6.5, 4.5], [2, -6, 3.5], [-6.5, -3, 3]].forEach(([x, y, len], i) => {
      const base = at([x, y]);
      const dir = rot([x * 0.4, -1], A), n = Math.hypot(...dir), d = [dir[0] / n, dir[1] / n];
      const perp = [-d[1] * 2.2, d[0] * 2.2];
      const l = len + Math.sin(p.t * 6 + i) * bounce * 0.6;
      poly([add(base, perp), add(base, mul(perp, -1)), add(base, mul(d, l))], i % 2 ? C.woolTip.base : C.wool.base, "head");
    });
    hornChain([at([2, -3]), at([6, -4.5]), at([7.5, -8]), at([6, -10.5])], "hornF");
    if (gear.headband) {
      const flap = Math.sin(p.t * 9) * 1.5;
      capsule(at([-7, -1]), at([-11, 1 + flap]), 1.2, 0.8, C.blue, "band");
      capsule(at([-6, -2.5]), at([4, -3.5]), 1.5, 1.5, C.blue, "band");
    }
  }

  function hornChain(pts, group) {
    const r = [2.4, 1.9, 1.4, 0.8];
    for (let i = 0; i < pts.length - 1; i++) capsule(pts[i], pts[i + 1], r[i], r[i + 1], C.horn, group);
  }

  function face(sk, p) {
    const h = sk.head, A = sk.headAng, at = (v) => add(h, rot(v, A));
    const e = at([4, -0.5]);
    const ex = Math.round(e[0]), ey = Math.round(e[1]);
    if (p.eye === "closed") {
      px(ex - 1, ey, PUPIL); px(ex, ey, PUPIL); px(ex + 1, ey + 1, PUPIL);
    } else {
      px(ex, ey, EYE); px(ex + 1, ey, PUPIL); px(ex - 1, ey, EYE); px(ex, ey + 1, EYE); px(ex + 1, ey + 1, PUPIL);
      if (p.eye === "half") { px(ex - 1, ey, LID); px(ex, ey, LID); px(ex + 1, ey, LID); px(ex, ey + 1, EYE); px(ex + 1, ey + 1, PUPIL); }
      if (p.eye === "angry") { px(ex - 1, ey - 2, PUPIL); px(ex, ey - 1, PUPIL); px(ex + 1, ey - 1, PUPIL); }
      if (p.eye === "open") { px(ex - 1, ey - 1, PUPIL); px(ex, ey - 2, PUPIL); px(ex + 1, ey - 2, PUPIL); }
    }
    const n = at([12.5, 3]);
    px(n[0], n[1] + 1, PUPIL);
    px(n[0], n[1], PUPIL);
    const m = at([10, 6.5]);
    if (p.mouth === "yawn") {
      for (let i = -1; i <= 1; i++) for (let j = 0; j <= 2; j++) px(m[0] + i, m[1] + j, MOUTH);
      px(m[0], m[1] + 1, hex("#e06070"));
    } else if (p.mouth === "grin") {
      px(m[0] - 1, m[1], PUPIL); px(m[0], m[1], WHITE); px(m[0] + 1, m[1], WHITE); px(m[0] + 2, m[1] - 1, PUPIL);
    } else if (p.mouth === "pant") {
      px(m[0], m[1], MOUTH); px(m[0] + 1, m[1], MOUTH); px(m[0] + 1, m[1] + 1, hex("#e06070"));
    }
  }

  function bibNumber(sk) {
    const o = add(add(sk.hip, mul(sk.u, 9)), rot([1.5, -2], sk.lean));
    ["#.###", "#.#.#", "#.###", "#...#", "#.###"].forEach((row, j) =>
      [...row].forEach((ch, i) => { if (ch === "#") px(o[0] + i, o[1] + j, PUPIL); }));
  }

  function body(sk, p, gear) {
    const { hip, u, lean } = sk, at = (v, k) => add(add(hip, mul(u, k)), rot(v, lean));
    const puff = p.puff || 0;
    ellipse(...at([0, 0], 6.5), 8.5, 7.5, lean, C.fur, "body");
    ellipse(...at([3.5, 0], 6.5), 4, 5, lean, C.belly, "belly");
    // the hump: a big woolly mound over the shoulders, fringed with tufts
    ellipse(...at([-2, 0], 21), 10 + puff * 0.5, 8, lean - 0.2, C.wool, "body");
    ellipse(...at([1, 0], 15), 12 + puff, 9.5 + puff * 0.6, lean, C.wool, "body");
    capsule(sk.neck, add(sk.head, rot([-3, 2], sk.headAng)), 7, 6, C.wool, "body");
    [[-10, 22], [-7, 27], [-3, 29], [1, 28], [-12, 16], [-12, 10]].forEach(([x, k], i) => {
      const base = at([x, 0], k), d = rot([x < -9 ? -1 : -0.3, x < -9 ? 0.2 : -1], lean);
      const perp = [-d[1] * 2.4, d[0] * 2.4], len = 3.5 + (i % 2) + Math.sin(p.t * 6 + i) * (p.maneBounce || 0) * 0.5;
      poly([add(base, perp), add(base, mul(perp, -1)), add(base, mul(d, len))], i % 2 ? C.woolTip.base : C.wool.base, "body");
    });
    ellipse(...at([6, 2], 14), 4.5 + puff * 0.4, 4, lean, C.woolTip, "chest");
    if (gear.bib) {
      poly([at([0, -3], 9), at([8, -3], 9), at([8, 3], 9), at([0, 3], 9)], C.white.base, "bib");
    }
    if (gear.medal) {
      capsule(at([-2, -6], 15), at([3, 2], 10), 0.6, 0.6, C.red, "medal");
      ellipse(...at([3, 3], 9), 2.2, 2.2, 0, C.gold, "medal");
    }
  }

  function loin(sk, p) {
    const { hip, lean } = sk, at = (v) => add(hip, rot(v, lean));
    // black shorts: seat over the hips, legs are drawn with each thigh
    ellipse(...at([0.5, 2]), 8.5, 4.5, lean, C.shorts, "shortsF");
    capsule(at([-7, -1]), at([7.5, -1]), 2, 2, C.shorts, "waist");
  }

  function bison(p, gear) {
    const sk = skeleton(p);
    arm(sk.shB, sk.elB, sk.haB, C.furBack, "B", gear, p.flex);
    leg(sk.hipB, sk.knB, sk.ftB, C.furBack, "B");
    if (p.propBehind) p.propBehind(sk);
    body(sk, p, gear);
    leg(sk.hipF, sk.knF, sk.ftF, C.fur, "F");
    loin(sk, p);
    head(sk, p, gear);
    if (p.propMid) p.propMid(sk);
    arm(sk.shF, sk.elF, sk.haF, C.fur, "F", gear, p.flex);
    if (p.propFront) p.propFront(sk);
    return sk;
  }

  // ---------- poses and animations ----------

  const SPEED = { exhausted: 0.55, tired: 0.78, ready: 1, fired_up: 1.2 };
  const EYE_FOR = { exhausted: "half", tired: "half", ready: "open", fired_up: "angry" };
  const SLUMP = { exhausted: 0.22, tired: 0.12, ready: 0, fired_up: -0.04 };

  function base(mood, t) {
    return { t, eye: EYE_FOR[mood], mouth: mood === "fired_up" ? "grin" : mood === "exhausted" ? "pant" : "", tilt: SLUMP[mood] * 1.5, maneBounce: 0 };
  }

  function standing(t, mood) {
    const p = base(mood, t);
    const breathe = Math.sin(t * (mood === "exhausted" ? 1.4 : 2.2));
    const slump = SLUMP[mood];
    p.hip = [X0, 56 + slump * 6 + breathe * 0.4];
    p.lean = 0.06 + slump;
    p.footF = [X0 + 4, GROUND];
    p.footB = [X0 - 4, GROUND];
    const sk = skeleton({ ...p, handF: [0, 0], handB: [0, 0] });
    p.handF = add(sk.shF, [2 + slump * 10, 15]);
    p.handB = add(sk.shB, [3 + slump * 10, 15]);
    p.puff = breathe * 0.3;
    return p;
  }

  function moodPose(t, mood) {
    const p = standing(t, mood);
    if (mood === "fired_up") {
      // double-biceps flex, bouncing on the toes
      const bounce = Math.abs(Math.sin(t * 5)) * 1.5, squeeze = (Math.sin(t * 3) + 1) / 2;
      p.hip = [X0, 55 - bounce];
      p.lean = -0.02;
      const sk = skeleton({ ...p, handF: [0, 0], handB: [0, 0] });
      p.handF = add(sk.shF, [-7.5 + squeeze, -8]);
      p.handB = add(sk.shB, [7.5 - squeeze, -8]);
      p.elbowF = [-1, 1];
      p.elbowB = [1, 1];
      p.flex = 1 + squeeze * 0.6;
      p.puff = 1 + squeeze * 0.8;
      p.maneBounce = 1.2;
      p.fx = ["steam", "sparkle"];
    } else if (mood === "ready") {
      // shaking out the arms, light bounce
      const b = Math.abs(Math.sin(t * 4));
      p.hip[1] -= b;
      p.handF = add(p.handF, [Math.sin(t * 12) * 2, -2]);
      p.handB = add(p.handB, [Math.sin(t * 12 + 1) * 2, -2]);
      p.maneBounce = 0.6;
    } else if (mood === "tired") {
      p.mouth = (t % 4) < 1.4 ? "yawn" : "";
      p.tilt = (t % 4) < 1.4 ? -0.35 : 0.3;
      p.fx = ["sweat"];
    } else {
      // dozing on his feet
      const nod = (Math.sin(t * 1.2) + 1) / 2;
      p.tilt = 0.25 + nod * 0.35;
      p.eye = "closed";
      p.mouth = "";
      p.fx = ["zzz"];
    }
    return p;
  }

  function run(t, mood, sprint) {
    const sp = SPEED[mood];
    const cad = (sprint ? 2.6 : 1.7) * sp, ph = t * cad * Math.PI * 2;
    const stride = (sprint ? 9 : 6) * (0.6 + sp * 0.4), lift = sprint ? 5 : 3;
    const p = base(mood, t);
    p.lean = (sprint ? 0.28 : 0.14) + SLUMP[mood];
    p.hip = [X0, 55 - Math.abs(Math.sin(ph)) * (sprint ? 2 : 1.2) + SLUMP[mood] * 5];
    const foot = (q) => [X0 + 2 + Math.sin(q) * stride, GROUND - Math.max(0, Math.cos(q)) * lift];
    p.footF = foot(ph);
    p.footB = foot(ph + Math.PI);
    const sk = skeleton({ ...p, handF: [0, 0], handB: [0, 0] });
    const swing = sprint ? 7 : 4;
    p.handF = add(sk.shF, [-Math.sin(ph) * swing + 3, sprint ? 9 : 11]);
    p.handB = add(sk.shB, [Math.sin(ph) * swing + 3, sprint ? 9 : 11]);
    p.elbowF = p.elbowB = [-1, 0.5];
    p.maneBounce = 1;
    p.scroll = (sprint ? 40 : 22) * sp;
    p.fx = ["dust", ...(sprint ? ["speed"] : [])];
    if (mood === "exhausted" || mood === "tired") p.fx.push("sweat");
    if (mood === "fired_up") p.fx.push("steam");
    p.dustFeet = [p.footF, p.footB];
    return p;
  }

  function sled(t, mood) {
    const sp = SPEED[mood];
    const ph = t * 1.3 * sp * Math.PI * 2;
    const p = base(mood, t);
    p.lean = 0.95 + SLUMP[mood] * 0.5;
    p.hip = [X0 - 4, 57 + SLUMP[mood] * 6];
    p.tilt = -0.55 + SLUMP[mood];
    const foot = (q) => [X0 - 4 + Math.sin(q) * 6, GROUND - Math.max(0, Math.cos(q)) * 2.5];
    p.footF = foot(ph);
    p.footB = foot(ph + Math.PI);
    const sledX = X0 + 18;
    p.handF = [sledX + 2, G - 21];
    p.handB = [sledX + 5, G - 22];
    p.elbowF = p.elbowB = [0, 1];
    p.scroll = 9 * sp * sp;
    p.fx = ["dust", ...(mood === "fired_up" ? ["steam"] : []), ...(sp < 1 ? ["sweat"] : [])];
    p.dustFeet = [p.footF, p.footB];
    p.propBehind = () => {
      // far pole, then the sled body and plates
      capsule([sledX + 5, G - 3], [sledX + 5, G - 22], 1, 1, C.metal, "sled");
    };
    p.propFront = () => {
      poly([[sledX - 1, G - 4], [sledX + 18, G - 4], [sledX + 20, G], [sledX - 2, G]], C.metal.base, "sledbase");
      ellipse(sledX + 10, G - 9, 6, 6, 0, C.ball, "plate");
      ellipse(sledX + 10, G - 9, 1.5, 1.5, 0, C.metal, "plate2");
      capsule([sledX + 2, G - 3], [sledX + 2, G - 21], 1.1, 1.1, C.metal, "sledpole");
      ellipse(p.handF[0], p.handF[1], 3.4, 3.2, 0, C.fur, "fistF");
    };
    return p;
  }

  const WB_TARGET = [X0 + 30, 14];
  function wallball(t, mood) {
    const sp = SPEED[mood];
    const period = 2.2 / sp, ph = (t % period) / period;
    const p0 = base(mood, t);
    const squat = { hip: [X0 - 2, 63 + SLUMP[mood] * 3], lean: 0.32, tilt: -0.2 };
    const stand = { hip: [X0, 55], lean: 0.05, tilt: -0.25 };
    const k = kf([[0, stand], [0.38, squat], [0.48, squat], [0.58, stand], [1, stand]], ph);
    const p = { ...p0, ...k, footF: [X0 + 5, GROUND], footB: [X0 - 3, GROUND] };
    const sk = skeleton({ ...p, handF: [0, 0], handB: [0, 0] });
    // hands relative to the shoulder: chest, squat, drive overhead, follow through, catch
    const h = kf([[0, { h: [11, 2] }], [0.38, { h: [12, 4] }], [0.48, { h: [11, 0] }], [0.56, { h: [6, -14] }],
      [0.7, { h: [6, -13] }], [0.86, { h: [11, -2] }], [1, { h: [11, 2] }]], ph).h;
    const hold = add(sk.shF, h);
    p.handF = add(hold, [-2, 1]);
    p.handB = add(hold, [2, -1]);
    p.elbowF = p.elbowB = [-0.3, 1];
    const reach = mood === "exhausted" ? 0.45 : mood === "tired" ? 0.85 : 1;
    let ball = add(hold, [2, -1]);
    if (ph >= 0.56 && ph < 0.86) {
      const q = (ph - 0.56) / 0.3;
      const from = add(sk.shF, [8, -17]), to = add(sk.shF, [13, -3]);
      const peak = [lerp(from[0], WB_TARGET[0] + 2, reach), lerp(from[1], WB_TARGET[1], reach)];
      ball = q < 0.45 ? lerp2(from, peak, 1 - (1 - q / 0.45) ** 2) : lerp2(peak, to, ((q - 0.45) / 0.55) ** 2);
      p.hit = reach === 1 && q > 0.35 && q < 0.6;
    }
    p.fx = mood === "fired_up" ? ["steam"] : mood === "ready" ? [] : ["sweat"];
    p.propBehind = () => {
      capsule([WB_TARGET[0] + 6, 4], [WB_TARGET[0] + 6, G], 0.8, 0.8, C.metal, "wall");
      poly([[WB_TARGET[0] - 1, WB_TARGET[1] - 4], [WB_TARGET[0] + 5, WB_TARGET[1] - 4], [WB_TARGET[0] + 5, WB_TARGET[1] + 4], [WB_TARGET[0] - 1, WB_TARGET[1] + 4]],
        p.hit ? C.volt.hi : C.volt.sh, "target");
    };
    p.propFront = () => ellipse(ball[0], ball[1], 4, 4, 0, C.ball, "ball");
    return p;
  }

  function burpee(t, mood) {
    const sp = SPEED[mood];
    const period = 2.6 / sp, ph = (t % period) / period;
    const up = { hip: [X0, 55], lean: 0.05, tilt: -0.2, hF: [X0 + 6, 66], hB: [X0 + 8, 66], fF: [X0 + 4, GROUND], fB: [X0 - 3, GROUND] };
    const crouch = { hip: [X0 - 2, 64], lean: 0.9, tilt: -0.9, hF: [X0 + 12, GROUND - 1], hB: [X0 + 14, GROUND - 1], fF: [X0 + 3, GROUND], fB: [X0 - 2, GROUND] };
    const plank = { hip: [X0 - 6, 66], lean: 1.42, tilt: -1.2, hF: [X0 + 13, GROUND - 1], hB: [X0 + 15, GROUND - 1], fF: [X0 - 22, GROUND], fB: [X0 - 21, GROUND] };
    const floor = { ...plank, hip: [X0 - 6, 69], lean: 1.55, tilt: -1.35 };
    const jump = { hip: [X0 + 3, 46], lean: -0.05, tilt: -0.3, hF: [X0 + 4, 20], hB: [X0 + 8, 21], fF: [X0 + 5, GROUND - 9], fB: [X0 - 1, GROUND - 8] };
    const frames = [[0, up], [0.14, crouch], [0.26, plank], [0.36, floor], [0.48, plank], [0.6, crouch], [0.72, jump], [0.86, up], [1, up]];
    const k = kf(frames, ph);
    const p = { ...base(mood, t), hip: k.hip, lean: k.lean, tilt: k.tilt + SLUMP[mood], handF: k.hF, handB: k.hB, footF: k.fF, footB: k.fB };
    p.elbowF = p.elbowB = ph > 0.62 && ph < 0.8 ? [-1, 0] : [-0.6, 1];
    p.kneeF = p.kneeB = [1, -0.6];
    p.maneBounce = 1.2;
    p.fx = mood === "fired_up" ? ["steam"] : mood === "ready" ? [] : ["sweat"];
    if (ph > 0.8 && ph < 0.92) { p.fx.push("dust"); p.dustFeet = [k.fF, k.fB]; }
    return p;
  }

  function sitting(t, mood, recover) {
    const p = base(mood, t);
    p.hip = [X0 - 4, G - 4];
    p.lean = -0.18 + SLUMP[mood];
    p.footF = [X0 + 13, GROUND];
    p.footB = [X0 + 16, GROUND];
    p.kneeF = p.kneeB = [0.3, -1];
    p.tilt = -0.05 + SLUMP[mood];
    const sk = skeleton({ ...p, handF: [0, 0], handB: [0, 0] });
    p.handB = [X0 - 12, G - 3];
    p.handF = [X0 - 14, G - 3];
    p.elbowF = p.elbowB = [-1, 0];
    p.fx = [];
    if (recover) {
      const sip = (t % 5) < 1.6;
      p.handF = sip ? add(sk.head, rot([7, 5], 0)) : add(sk.shF, [9, 8]);
      p.elbowF = [0.2, 1];
      p.tilt = sip ? -0.45 : p.tilt;
      p.propFront = () => {
        const h = p.handF, ang = sip ? -1.1 : 0;
        capsule(add(h, rot([0, 4], ang)), add(h, rot([0, -6], ang)), 2.6, 2.6, C.sweat, "bottle");
        capsule(add(h, rot([0, -7], ang)), add(h, rot([0, -9], ang)), 1.6, 1.6, C.volt, "cap");
        ellipse(h[0], h[1], 3.4, 3.2, 0, C.fur, "fistF2");
      };
    }
    if (mood === "exhausted" || (mood === "tired" && !recover)) {
      p.eye = "closed";
      p.tilt = 0.35 + Math.sin(t * 1.2) * 0.1;
      p.mouth = "";
      p.fx = ["zzz"];
    }
    return p;
  }

  // What he does on each kind of day. Workouts alternate with a mood pose so you
  // can read both at a glance.
  const WORKOUT = {
    sprint: (t, m) => run(t, m, true),
    jog: (t, m) => run(t, m, false),
    sled,
    skill: (t, m) => ((t % 12) < 6 ? wallball(t, m) : burpee(t, m)),
    sim: (t, m) => [(x) => run(x, m, true), (x) => sled(x, m), (x) => wallball(x, m)][Math.floor(t / 4) % 3](t),
    race: moodPose,
    rest: (t, m) => sitting(t, m, false),
    recover: (t, m) => sitting(t, m, true),
  };
  const CYCLE = { work: 7.5, mood: 3.5 };

  function poseAt(t, state) {
    const work = WORKOUT[state.action] || WORKOUT.jog;
    if (state.action === "race" || state.only === "work") return work(t, state.mood);
    if (state.only === "mood") return moodPose(t, state.mood);
    const c = t % (CYCLE.work + CYCLE.mood);
    if (c < CYCLE.work) return work(t, state.mood);
    if (["rest", "recover"].includes(state.action) && state.mood !== "fired_up") return work(t, state.mood);
    return moodPose(t, state.mood);
  }

  // ---------- effects ----------

  const Z = ["####", "..#.", ".#..", "####"], Zs = ["###", ".#.", "###"];

  function fxBefore(p, sk, t) {
    if (p.fx?.includes("zzz")) {
      for (let k = 0; k < 3; k++) {
        const q = (t * 0.45 + k / 3) % 1;
        const at = add(sk.head, [4 + q * 12 + Math.sin((q + k) * 6) * 2, -12 - q * 18]);
        glyph(q > 0.4 ? Z : Zs, at[0], at[1], WHITE, "zzz" + k);
      }
    }
    if (p.fx?.includes("sweat")) {
      for (let k = 0; k < 2; k++) {
        const q = (t * 1.3 + k * 0.5) % 1;
        const o = add(sk.head, rot([-2, -6], sk.headAng));
        const at = add(o, [(k ? -1 : 1) * (2 + q * 9), -4 + q * q * 16 - q * 8]);
        ellipse(at[0], at[1], 1.1, 1.5, 0, C.sweat, "sweat" + k);
      }
    }
  }

  function fxAfter(p, sk, t) {
    const fx = p.fx || [];
    if (fx.includes("steam")) {
      for (let k = 0; k < 2; k++) {
        const q = (t * 1.4 + k * 0.5) % 1;
        const n = add(sk.head, rot([11, 3], sk.headAng));
        const c = add(n, [3 + q * 8, -q * 3 + k * 2]);
        const r = 1 + q * 2.5;
        for (let y = -3; y <= 3; y++) for (let x = -3; x <= 3; x++) {
          if (x * x + y * y <= r * r && (q < 0.5 || (x + y) % 2 === 0)) pxEmpty(c[0] + x, c[1] + y, STEAM);
        }
      }
    }
    if (fx.includes("sparkle")) {
      const spots = [[-14, -20], [16, -26], [-18, 0], [20, -6]];
      spots.forEach(([dx, dy], k) => {
        const q = (t * 1.6 + k * 0.37) % 1;
        if (q > 0.6) return;
        const c = add(sk.head, [dx, dy]), r = q < 0.3 ? 1 : 2;
        for (let i = -r; i <= r; i++) { pxEmpty(c[0] + i, c[1], VOLT); pxEmpty(c[0], c[1] + i, VOLT); }
      });
    }
    if (fx.includes("dust")) {
      (p.dustFeet || []).forEach((f, k) => {
        if (f[1] < GROUND - 0.5) return;
        for (let j = 0; j < 3; j++) {
          const q = (t * 2 + j / 3 + k * 0.5) % 1;
          pxEmpty(f[0] - 3 - q * 8, G - 1 - q * 3, DUST);
          if (q < 0.5) pxEmpty(f[0] - 4 - q * 8, G - 1 - q * 3, DUST);
        }
      });
    }
    if (fx.includes("speed")) {
      for (let k = 0; k < 4; k++) {
        const y = 40 + k * 8, off = ((t * 90 + k * 23) % 60);
        for (let i = 0; i < 6; i++) pxEmpty(X0 - 18 - off + i, y, hex("#3a3a3a"));
      }
    }
  }

  function ground(p, t) {
    // floor ticks scroll when he is moving
    const off = ((p.scroll || 0) * t) % 12;
    for (let x = -12; x < W + 12; x += 12) {
      const gx = Math.round(x - off);
      for (let i = 0; i < 4; i++) pxEmpty(gx + i, G + 1, hex("#2c2c2c"));
    }
    for (let x = 4; x < W - 4; x++) pxEmpty(x, G, hex("#222222"));
  }

  function shadowUnder(sk) {
    const cx = (sk.ftF[0] + sk.ftB[0]) / 2 + 1, rx = 11 + Math.abs(sk.ftF[0] - sk.ftB[0]) / 2;
    const lift = Math.max(0, GROUND - Math.max(sk.ftF[1], sk.ftB[1]));
    const r = rx - lift * 0.6;
    for (let y = G - 2; y <= G + 1; y++) for (let x = Math.floor(cx - r); x <= cx + r; x++) {
      const dx = (x + 0.5 - cx) / r, dy = (y + 0.5 - (G - 0.5)) / 2;
      if (dx * dx + dy * dy <= 1) pxEmpty(x, y, SHADOW);
    }
  }

  // ---------- frame + loop ----------

  function frame(ctx, img, t, state) {
    clear();
    const p = poseAt(t, state);
    const gear = Object.fromEntries((state.gear || []).filter((g) => g.earned).map((g) => [g.key, true]));
    if (state.action === "race") gear.bib = true;
    const sk = bison(p, gear);
    fxBefore(p, sk, t);
    outline();
    face(sk, p);
    if (gear.bib) bibNumber(sk);
    shadowUnder(sk);
    ground(p, t);
    fxAfter(p, sk, t);
    new Uint32Array(img.data.buffer).set(col);
    ctx.putImageData(img, 0, 0);
  }

  function mount(canvas, state) {
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(W, H);
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let cur = { ...state }, start = performance.now(), raf = 0, last = 0;
    const draw = (now) => {
      raf = requestAnimationFrame(draw);
      if (now - last < 1000 / 12) return;   // 12 fps, like a sprite sheet
      last = now;
      frame(ctx, img, (now - start) / 1000, cur);
    };
    if (reduce) frame(ctx, img, 1.2, { ...cur, only: "mood" });
    else raf = requestAnimationFrame(draw);
    return {
      set(next) { cur = { ...cur, ...next }; start = performance.now(); if (reduce) frame(ctx, img, 1.2, { ...cur, only: "mood" }); },
      stop() { cancelAnimationFrame(raf); },
      frame: (t, s) => frame(ctx, img, t, { ...cur, ...s }),
    };
  }

  window.Bison = { mount, W, H };
})();

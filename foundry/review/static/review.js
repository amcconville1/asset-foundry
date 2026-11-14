// The review page: scroll a round, turn each variant, like / cut / use / comment.
// Every change is saved to the catalog as it happens (POST /api/...).
import * as THREE from "three";
import { GLTFLoader } from "/static/vendor/loaders/GLTFLoader.js";
import { OrbitControls } from "/static/vendor/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const state = {
  config: null, collections: [], col: null, roundN: null, idx: 0,
  mode: "3d", markMode: null, compare: new Set(), undo: [], reviewer: "",
};

// ---- storage (a per-viewer convenience only; the catalog holds everything that matters)
function remember(key, value) { try { localStorage.setItem("foundry." + key, value); } catch (e) {} }
function recall(key) { try { return localStorage.getItem("foundry." + key); } catch (e) { return null; } }

// ---- data
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const round = () => state.col?.rounds.find((r) => r.n === state.roundN);
const variants = () => round()?.variants || [];
const current = () => variants()[state.idx];
const fileUrl = (v, f) => `/files/${state.col.name}/round-${state.roundN}/${v.id}/${f}`;
const mine = (v) => v.verdicts[state.reviewer] || {};

async function init() {
  state.config = await api("/api/config");
  state.reviewer = recall("reviewer") || state.config.reviewer || "";
  $("reviewer").value = state.reviewer;
  $("reviewer").addEventListener("change", () => { state.reviewer = $("reviewer").value.trim(); remember("reviewer", state.reviewer); render(); });
  state.collections = await api("/api/collections");
  const sel = $("collection");
  sel.innerHTML = state.collections.map((c) =>
    `<option value="${c.name}">${c.name}${c.waiting ? " (" + c.waiting + " waiting)" : ""}</option>`).join("");
  sel.addEventListener("change", () => load(sel.value));
  const [hashCol, hashRound, hashMode] = decodeURIComponent(location.hash.slice(1)).split("/");
  if (["3d", "sheet", "compare"].includes(hashMode)) state.mode = hashMode;
  const first = state.collections.find((c) => c.name === hashCol) || state.collections.find((c) => c.waiting) || state.collections[0];
  if (!first) { $("view").innerHTML = `<div class="empty">No collections in the catalog yet.</div>`; return; }
  sel.value = first.name;
  await load(first.name, hashRound ? Number(hashRound) : null);
  wire();
}

async function load(name, roundN = null, keepIdx = false) {
  state.col = await api("/api/collection/" + encodeURIComponent(name));
  const rs = state.col.rounds;
  const ready = rs.filter((r) => r.status === "ready");
  state.roundN = roundN ?? (ready.length ? ready[ready.length - 1].n : rs.length ? rs[rs.length - 1].n : null);
  if (!keepIdx) { state.idx = 0; state.compare.clear(); }
  history.replaceState(null, "", `#${name}/${state.roundN ?? ""}/${state.mode}`);
  render(true);
}

// ---- rendering
function render(viewToo = false) {
  renderHeader();
  renderStrip();
  renderSide();
  if (viewToo) renderView();
}

function renderHeader() {
  const rs = state.col.rounds;
  $("rounds").innerHTML = rs.map((r) =>
    `<button data-round="${r.n}" class="${r.n === state.roundN ? "on" : ""}">Round ${r.n}</button>`).join(" ");
  $("rounds").querySelectorAll("button").forEach((b) => b.onclick = () => load(state.col.name, Number(b.dataset.round)));
  const r = round();
  $("status").textContent = r ? r.status : "no rounds";
  $("status").className = "chip " + (r?.status || "");
  $("reviewed").disabled = !r || r.status !== "ready";
}

function renderStrip() {
  $("strip").innerHTML = variants().map((v, i) => {
    const verdict = mine(v).verdict;
    return `<div class="thumb ${i === state.idx ? "sel" : ""} ${verdict ? "v-" + verdict : ""}" data-i="${i}">
      <img src="${fileUrl(v, "renders/front.png")}" alt="${v.id}" loading="lazy">
      <span class="id">${v.id.split("-")[1]}</span>
      ${verdict ? `<span class="badge ${verdict}">${verdict}</span>` : ""}
      <input type="checkbox" title="Compare (Space)" ${state.compare.has(v.id) ? "checked" : ""} data-c="${v.id}">
    </div>`;
  }).join("");
  $("strip").querySelectorAll(".thumb").forEach((el) => el.onclick = (e) => {
    if (e.target.matches("input")) { toggleCompare(e.target.dataset.c); return; }
    select(Number(el.dataset.i));
  });
}

function renderSide() {
  const v = current();
  const r = round();
  if (!v) { $("side").innerHTML = `<div class="muted">No variants in this round.</div>`; return; }
  const my = mine(v);
  const st = v.stats || {};
  const others = Object.entries(v.verdicts).filter(([by]) => by !== state.reviewer);
  const lin = v.lineage || {};
  $("side").innerHTML = `
    <div><h2>${v.id}</h2><div class="muted">${escapeHtml(lin.brief || "")}</div></div>
    ${lin.parents?.length ? `<div><h3>Made from</h3>${lin.parents.join(", ")}${lin.answers?.length ? `<div class="muted">answers: ${lin.answers.map(escapeHtml).join("; ")}</div>` : ""}</div>` : ""}
    <div><h3>Verdict</h3><div class="verdicts">
      <button class="like ${my.verdict === "like" ? "on" : ""}" data-v="like">Like <kbd>L</kbd></button>
      <button class="cut ${my.verdict === "cut" ? "on" : ""}" data-v="cut">Cut <kbd>X</kbd></button>
      <button class="use ${my.verdict === "use" ? "on" : ""}" data-v="use">Use <kbd>U</kbd></button>
    </div></div>
    <div><h3>What you like, or what to change</h3>
      <textarea id="comment" placeholder="e.g. the weight of this blade; guard too plain">${escapeHtml(my.comment || "")}</textarea>
      <div class="saved" id="saved"></div></div>
    ${others.length ? `<div class="others"><h3>Other reviewers</h3>${others.map(([by, o]) =>
      `<div><strong>${escapeHtml(by)}</strong>: ${o.verdict || "-"}${o.comment ? ` — ${escapeHtml(o.comment)}` : ""}</div>`).join("")}</div>` : ""}
    ${marksHtml(my)}
    <div><h3>Numbers</h3>
      <div>${st.tris ?? "?"} tris · ${(st.size || []).map((s) => s.toFixed(2)).join(" × ")} m</div>
      ${v.failed.length ? `<div class="fail">failed: ${v.failed.join(", ")}</div>` : `<div class="muted">rules pass</div>`}</div>
    <div><h3>Round ${r.n} note</h3>
      <textarea id="roundnote" placeholder="about the whole round, e.g. all too thin, try wider">${escapeHtml(r.notes?.[state.reviewer] || "")}</textarea>
      <div class="muted">${escapeHtml(r.brief || "")}</div></div>`;
  $("side").querySelectorAll(".verdicts button[data-v]").forEach((b) => b.onclick = () => verdict(b.dataset.v));
  wireMarks(v);
  autosave($("comment"), () => saveVerdict(v, mine(v).verdict ?? null, $("comment").value));
  autosave($("roundnote"), () => api("/api/round-note", { collection: state.col.name, round: r.n, by: state.reviewer, note: $("roundnote").value })
    .then(() => { r.notes = { ...(r.notes || {}), [state.reviewer]: $("roundnote").value }; }));
}

function renderView() {
  if (state.col) history.replaceState(null, "", `#${state.col.name}/${state.roundN ?? ""}/${state.mode}`);
  for (const id of ["tab3d", "tabsheet", "tabcompare"]) $(id).classList.toggle("on", { tab3d: "3d", tabsheet: "sheet", tabcompare: "compare" }[id] === state.mode);
  const v = current();
  const view = $("view");
  if (!v) { view.innerHTML = `<div class="empty">Nothing to show.</div>`; return; }
  if (state.mode === "sheet") {
    viewer.detach();
    view.innerHTML = `<img class="sheet" src="${fileUrl(v, "sheet.png")}" alt="sheet for ${v.id}">`;
  } else if (state.mode === "compare") {
    viewer.detach();
    const picked = variants().filter((x) => state.compare.has(x.id));
    const list = picked.length >= 2 ? picked : variants();
    const cols = Math.min(list.length, 4);
    const hint = picked.length < 2 ? `<div class="hint">All ${list.length} at the same scale. Tick two to four (Space) to compare just those.</div>` : "";
    view.innerHTML = `<div class="column">${hint}<div class="compare" style="grid-template-columns: repeat(${cols}, 1fr)">${list.map((x) =>
      `<figure><figcaption>${x.id} ${mine(x).verdict ? `<span class="badge ${mine(x).verdict}">${mine(x).verdict}</span>` : ""}</figcaption>
        <div class="pair"><img src="${fileUrl(x, "renders/front.png")}" alt=""><img src="${fileUrl(x, "renders/three_quarter.png")}" alt=""></div>
        <img src="${fileUrl(x, "renders/silhouette.png")}" alt="" style="background:#fff"></figure>`).join("")}</div></div>`;
  } else {
    viewer.show(view, fileUrl(v, "parts.glb"), tintsFor(state.col.family), mine(v).marks || [], addMark);
    viewer.setMode(state.markMode);
  }
}

function tintsFor(family) {
  return state.config.tints[family] || state.config.tints._default || {};
}

// ---- actions
function select(i) {
  if (i < 0 || i >= variants().length) return;
  state.idx = i;
  state.markMode = null;
  render(true);
  document.querySelector(".thumb.sel")?.scrollIntoView({ block: "nearest" });
}

async function verdict(v) {
  const x = current();
  if (!x) return;
  if (!state.reviewer) { $("reviewer").focus(); flash("Type your name first (top right)."); return; }
  const before = mine(x).verdict ?? null;
  const next = before === v ? null : v;
  state.undo.push({ id: x.id, verdict: before });
  await saveVerdict(x, next, $("comment")?.value ?? mine(x).comment ?? "");
  render(state.mode === "compare");
}

async function saveVerdict(x, v, comment) {
  const marks = mine(x).marks || [];
  x.verdicts[state.reviewer] = await api("/api/verdict", { collection: state.col.name, variant: x.id, by: state.reviewer, verdict: v, comment, marks });
  flash("Saved");
}

async function undo() {
  const last = state.undo.pop();
  if (!last) return;
  const x = variants().find((v) => v.id === last.id);
  if (!x) return;
  await saveVerdict(x, last.verdict, mine(x).comment || "");
  state.idx = variants().indexOf(x);
  render(true);
}

function toggleCompare(id) {
  state.compare.has(id) ? state.compare.delete(id) : state.compare.size < 4 && state.compare.add(id);
  render(state.mode === "compare");
}

async function markReviewed() {
  const r = round();
  const open = r.variants.filter((v) => !mine(v).verdict).map((v) => v.id);
  const msg = open.length ? `${open.length} without a verdict (${open.join(", ")}). Mark round ${r.n} reviewed anyway?`
    : `Mark round ${r.n} reviewed? The agents start the next round from your notes.`;
  if (!confirm(msg)) return;
  await api("/api/reviewed", { collection: state.col.name, round: r.n });
  await load(state.col.name, r.n, true);
  flash("Round reviewed");
}

function autosave(el, save) {
  if (!el) return;
  let t = null;
  el.addEventListener("input", () => { clearTimeout(t); t = setTimeout(save, 600); });
  el.addEventListener("blur", () => { clearTimeout(t); save(); });
}

function flash(text) {
  const el = $("saved");
  if (el) { el.textContent = text; setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 1500); }
}

function wire() {
  $("tab3d").onclick = () => { state.mode = "3d"; renderView(); };
  $("tabsheet").onclick = () => { state.mode = "sheet"; renderView(); };
  $("tabcompare").onclick = () => { state.mode = "compare"; renderView(); };
  $("reviewed").onclick = markReviewed;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (e.target.matches("textarea, input, select")) e.target.blur();
      if (state.markMode) setMarkMode(null);
      return;
    }
    if (e.target.matches("textarea, input, select")) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    const acts = {
      arrowright: () => select(state.idx + 1), arrowdown: () => select(state.idx + 1), j: () => select(state.idx + 1),
      arrowleft: () => select(state.idx - 1), arrowup: () => select(state.idx - 1), k: () => select(state.idx - 1),
      l: () => verdict("like"), x: () => verdict("cut"), u: () => verdict("use"),
      0: () => { const v = mine(current()).verdict; if (v) verdict(v); },
      c: () => $("comment")?.focus(), z: () => undo(),
      s: () => { state.mode = state.mode === "3d" ? "sheet" : "3d"; renderView(); },
      v: () => { state.mode = state.mode === "compare" ? "3d" : "compare"; renderView(); },
      " ": () => current() && toggleCompare(current().id),
      p: () => setMarkMode("pin"), d: () => setMarkMode("drag"), a: () => setMarkMode("area"),
    };
    if (acts[k]) { e.preventDefault(); acts[k](); }
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- marks: pin (P), arrow (D), lasso (A); saved as part terms by the server
function setMarkMode(mode) {
  if (mode && state.mode !== "3d") { state.mode = "3d"; renderView(); }
  state.markMode = state.markMode === mode ? null : mode;
  viewer.setMode(state.markMode);
  renderSide();
}

async function addMark(m) {
  const x = current();
  if (!x) return;
  if (!state.reviewer) { $("reviewer").focus(); flash("Type your name first (top right)."); return; }
  const marks = [...(mine(x).marks || [])];
  m.n = marks.reduce((hi, k) => Math.max(hi, k.n || 0), 0) + 1;
  m.note = "";
  marks.push(m);
  await saveMarks(x, marks);
  renderSide();
  document.querySelector(`textarea[data-mark="${m.n}"]`)?.focus();
}

let saving = Promise.resolve();
function saveMarks(x, marks) {
  // One save at a time, each sending the latest list, so quick edits can't overwrite each other.
  setLocalMarks(x, marks);
  saving = saving.then(async () => {
    const my = mine(x);
    const sent = my.marks || [];
    const out = await api("/api/verdict", { collection: state.col.name, variant: x.id, by: state.reviewer,
      verdict: my.verdict ?? null, comment: $("comment")?.value ?? my.comment ?? "", marks: sent });
    const notes = new Map((mine(x).marks || []).map((m) => [m.n, m.note]));  // typed while saving
    out.marks = (out.marks || []).map((m) => ({ ...m, note: notes.get(m.n) ?? m.note }));
    x.verdicts[state.reviewer] = out;
    if (x === current()) viewer.setMarks(out.marks);
    flash("Saved");
  }).catch((e) => flash("Not saved: " + e.message));
  return saving;
}

function setLocalMarks(x, marks) {
  x.verdicts[state.reviewer] = { ...mine(x), marks };
}

function markSummary(m) {
  const at = (o) => Object.entries(o || {}).map(([k, v]) => `${k} ${(+v).toFixed(2)}`).join(", ");
  if (m.kind === "pin") return `${m.part}: ${at(m.at)}`;
  if (m.kind === "drag") return `${m.part}: ${m.metres >= 0 ? "+" : ""}${(+m.metres).toFixed(3)} m along ${m.axis}${m.param ? ` (${m.param})` : ""}`;
  return (m.parts || []).join(", ") || "no parts";
}

function marksHtml(my) {
  const tools = [["pin", "Pin", "P"], ["drag", "Arrow", "D"], ["area", "Lasso", "A"]].map(([k, label, key]) =>
    `<button data-tool="${k}" class="${state.markMode === k ? "on" : ""}">${label} <kbd>${key}</kbd></button>`).join("");
  const hint = { pin: "Click the model where you mean.", drag: "Drag from a spot to where it should go.", area: "Draw round the parts you mean." }[state.markMode] || "Point at what you mean; each mark gets a note.";
  const list = (my.marks || []).map((m) => `<div class="mark">
      <div><strong>${m.n}</strong> <span class="muted">${m.kind === "drag" ? "arrow" : m.kind === "area" ? "lasso" : "pin"} · ${escapeHtml(markSummary(m))}</span>
        <button class="del" data-del="${m.n}" title="Remove mark">✕</button></div>
      <textarea data-mark="${m.n}" placeholder="what about here?">${escapeHtml(m.note || "")}</textarea></div>`).join("");
  return `<div><h3>Marks</h3><div class="verdicts">${tools}</div><div class="help">${hint} <kbd>Esc</kbd> stops.</div>${list}</div>`;
}

function wireMarks(x) {
  $("side").querySelectorAll("[data-tool]").forEach((b) => b.onclick = () => setMarkMode(b.dataset.tool));
  $("side").querySelectorAll("[data-del]").forEach((b) => b.onclick = () =>
    saveMarks(x, (mine(x).marks || []).filter((m) => m.n !== Number(b.dataset.del))).then(renderSide));
  $("side").querySelectorAll("textarea[data-mark]").forEach((el) => {
    const n = Number(el.dataset.mark);
    el.addEventListener("input", () => setLocalMarks(x, (mine(x).marks || []).map((m) => m.n === n ? { ...m, note: el.value } : m)));
    autosave(el, () => saveMarks(x, mine(x).marks || []));
  });
}

// ---- 3D viewer: one renderer, reused; the per-part model so a click knows its part
const viewer = (() => {
  let renderer, scene, camera, controls, model = null, host = null, loading = 0, mode = null;
  let overlay, svg, markGroup, labels = [], meshes = [], drag = null, lasso = null;
  const loader = new GLTFLoader();
  const ray = new THREE.Raycaster();
  let onMark = () => {};

  function setup() {
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x2b2d31);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3a40, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 2.2);
    sun.position.set(2, 4, 3);
    scene.add(sun);
    markGroup = new THREE.Group();
    scene.add(markGroup);
    camera = new THREE.PerspectiveCamera(35, 1, 0.01, 200);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `<svg class="lasso"></svg>`;
    svg = overlay.querySelector("svg");
    const c = renderer.domElement;
    c.addEventListener("pointerdown", down);
    c.addEventListener("pointermove", move);
    c.addEventListener("pointerup", up);
    new ResizeObserver(resize).observe(document.body);
    renderer.setAnimationLoop(() => {
      if (!host) return;
      controls.update();
      renderer.render(scene, camera);
      placeLabels();
    });
  }
  function resize() {
    if (!host) return;
    const w = host.clientWidth, h = host.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(h, 1);
    camera.updateProjectionMatrix();
  }
  function partOf(obj) {
    while (obj.parent && obj.parent !== model) obj = obj.parent;
    return obj.name;
  }
  function ndc(e) {
    const r = renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  }
  function hit(e) {
    ray.setFromCamera(ndc(e), camera);
    return ray.intersectObjects(meshes, false)[0] || null;
  }
  function screen(p) {
    const v = p.clone().project(camera);
    const r = renderer.domElement.getBoundingClientRect();
    return { x: (v.x + 1) / 2 * r.width, y: (1 - v.y) / 2 * r.height, front: v.z < 1 };
  }
  function local(e) {
    const r = renderer.domElement.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }
  const arr = (v) => [+v.x.toFixed(5), +v.y.toFixed(5), +v.z.toFixed(5)];

  function down(e) {
    if (!mode) return;
    e.preventDefault();
    if (mode === "pin") {
      const h = hit(e);
      if (h) onMark({ kind: "pin", part: partOf(h.object), point: arr(h.point) });
    } else if (mode === "drag") {
      const h = hit(e);
      if (!h) return;
      const normal = camera.getWorldDirection(new THREE.Vector3());
      drag = { part: partOf(h.object), from: h.point.clone(), plane: new THREE.Plane().setFromNormalAndCoplanarPoint(normal, h.point), helper: null };
      renderer.domElement.setPointerCapture(e.pointerId);
    } else if (mode === "area") {
      lasso = [local(e)];
      renderer.domElement.setPointerCapture(e.pointerId);
    }
  }
  function move(e) {
    if (drag) {
      ray.setFromCamera(ndc(e), camera);
      const to = ray.ray.intersectPlane(drag.plane, new THREE.Vector3());
      if (!to) return;
      drag.to = to;
      if (drag.helper) markGroup.remove(drag.helper);
      drag.helper = arrow(drag.from, to, 0xffd166);
      markGroup.add(drag.helper);
    } else if (lasso) {
      lasso.push(local(e));
      svg.innerHTML = `<polyline points="${lasso.map((p) => `${p.x},${p.y}`).join(" ")}"/>`;
    }
  }
  function up() {
    if (drag) {
      const d = drag;
      drag = null;
      if (d.helper) markGroup.remove(d.helper);
      if (d.to && d.to.distanceTo(d.from) > 0.005) onMark({ kind: "drag", part: d.part, from: arr(d.from), to: arr(d.to) });
    } else if (lasso) {
      const poly = lasso;
      lasso = null;
      svg.innerHTML = "";
      if (poly.length < 3) return;
      const parts = partsInside(poly);
      if (parts.length) onMark({ kind: "area", parts });
    }
  }
  function inside(pt, poly) {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const a = poly[i], b = poly[j];
      if ((a.y > pt.y) !== (b.y > pt.y) && pt.x < (b.x - a.x) * (pt.y - a.y) / (b.y - a.y) + a.x) c = !c;
    }
    return c;
  }
  function partsInside(poly) {
    const found = new Map();
    const v = new THREE.Vector3();
    for (const m of meshes) {
      const pos = m.geometry.attributes.position;
      let n = 0;
      for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld);
        if (inside(screen(v), poly)) n++;
      }
      const id = partOf(m);
      const prev = found.get(id) || { n: 0, total: 0 };
      found.set(id, { n: prev.n + n, total: prev.total + pos.count });
    }
    // a part counts when a quarter of its corners fall inside the loop
    return [...found].filter(([, c]) => c.n / Math.max(c.total, 1) >= 0.25).map(([id]) => id);
  }
  function arrow(a, b, color) {
    const dir = b.clone().sub(a);
    const len = dir.length();
    const helper = new THREE.ArrowHelper(dir.normalize(), a, len, color, Math.min(len * 0.3, 0.08), Math.min(len * 0.15, 0.04));
    helper.traverse((o) => { if (o.material) { o.material.depthTest = false; o.material.transparent = true; } o.renderOrder = 10; });
    return helper;
  }

  function setMarks(marks) {
    if (!scene) return;
    markGroup.clear();
    labels.forEach((l) => l.el.remove());
    labels = [];
    for (const m of meshes) m.material.emissive?.setHex(0x000000);
    const size = model ? new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3()).length() : 1;
    for (const m of marks) {
      let at = null;
      if (m.kind === "pin" && m.point) {
        at = new THREE.Vector3(...m.point);
        const dot = new THREE.Mesh(new THREE.SphereGeometry(size * 0.008, 12, 8), new THREE.MeshBasicMaterial({ color: 0xff5d73, depthTest: false }));
        dot.position.copy(at);
        dot.renderOrder = 10;
        markGroup.add(dot);
      } else if (m.kind === "drag" && m.from && m.to) {
        const a = new THREE.Vector3(...m.from), b = new THREE.Vector3(...m.to);
        markGroup.add(arrow(a, b, 0xffd166));
        at = a.clone().lerp(b, 0.5);
      } else if (m.kind === "area") {
        const hits = meshes.filter((x) => (m.parts || []).includes(partOf(x)));
        hits.forEach((x) => x.material.emissive?.setHex(0x1d5fa8));
        if (hits.length) at = new THREE.Box3().setFromObject(hits[0]).getCenter(new THREE.Vector3());
      }
      if (at) {
        const el = document.createElement("div");
        el.className = "label";
        el.textContent = m.n;
        overlay.appendChild(el);
        labels.push({ el, at });
      }
    }
  }
  function placeLabels() {
    for (const l of labels) {
      const s = screen(l.at);
      l.el.style.transform = `translate(${s.x + 6}px, ${s.y - 22}px)`;
      l.el.style.display = s.front ? "" : "none";
    }
  }

  function show(el, url, tints, marks, markHandler) {
    if (!renderer) setup();
    onMark = markHandler;
    if (host !== el || !el.contains(renderer.domElement)) {
      el.innerHTML = "";
      el.appendChild(renderer.domElement);
      el.appendChild(overlay);
    }
    host = el;
    resize();
    const ticket = ++loading;
    loader.load(url, (gltf) => {
      if (ticket !== loading) return;  // a newer variant was picked meanwhile
      if (model) scene.remove(model);
      model = gltf.scene;
      meshes = [];
      model.traverse((o) => {
        if (o.isMesh) {
          const name = o.material?.name || "";
          const t = tints[name] || [0.6, 0.6, 0.6];
          o.material = new THREE.MeshStandardMaterial({ color: new THREE.Color(...t), flatShading: true, roughness: 0.7, name });
          meshes.push(o);
        }
      });
      scene.add(model);
      model.updateMatrixWorld(true);
      frame(model);
      setMarks(marks);
    }, undefined, () => { el.innerHTML = `<div class="empty">No parts.glb for this variant.</div>`; host = null; });
  }
  function frame(obj) {
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    const r = Math.max(size.x, size.y, size.z);
    camera.position.copy(centre).add(new THREE.Vector3(r * 0.9, r * 0.45, r * 1.5));
    camera.near = r / 100; camera.far = r * 50; camera.updateProjectionMatrix();
    controls.target.copy(centre);
    controls.update();
  }
  function setMode(m) {
    mode = m;
    if (!renderer) return;
    controls.enabled = !m;
    renderer.domElement.style.cursor = m ? "crosshair" : "";
  }
  function detach() { host = null; }
  return { show, detach, setMode, setMarks };
})();

init().catch((e) => { $("view").innerHTML = `<div class="empty">Could not load: ${escapeHtml(e.message)}</div>`; });

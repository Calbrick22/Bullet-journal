// Progressive enhancement: in-place updates, dialogs and keyboard shortcuts.
// Without it every form still posts and redirects.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// --- In-place updates --------------------------------------------------------

// POST, follow the redirect, and swap in the new #content. Returns false if the
// server refused (e.g. empty text), so callers can fall back.
async function post(url, data) {
  let res;
  try {
    res = await fetch(url, { method: "POST", body: data });
  } catch {
    return false;
  }
  if (!res.ok) return false;
  const doc = new DOMParser().parseFromString(await res.text(), "text/html");
  const fresh = doc.getElementById("content");
  if (!fresh) return location.reload();
  $("#content").replaceWith(fresh);
  document.title = doc.title;
  return true;
}

function focusEntry(id) {
  const li = document.getElementById(`e${id}`);
  if (li) li.focus({ preventScroll: false });
  return li;
}

document.addEventListener("submit", async (ev) => {
  const form = ev.target.closest("form[data-inline]");
  if (!form) return;
  ev.preventDefault();
  const focusId = document.activeElement?.id;
  const entryId = form.dataset.entry || document.activeElement?.closest?.("li.entry")?.dataset.id;
  const composer = form.hasAttribute("data-composer");
  const kind = form.querySelector("input[name=kind]:checked")?.value;
  const target = form.querySelector("select[name=target]")?.value;
  const dialog = form.closest("dialog");

  if (!(await post(form.action, new FormData(form)))) {
    if (dialog) return dialog.querySelector("[name=text], [name=on]")?.focus();
    return form.submit();
  }
  dialog?.close();
  if (composer) {
    // Keep adding: same kind, same day, cursor back in the box.
    const f = $("[data-composer]");
    if (!f) return;
    if (kind) f.querySelector(`input[name=kind][value="${kind}"]`).checked = true;
    const sel = f.querySelector("select[name=target]");
    if (sel && target) sel.value = target;
    f.querySelector("input[name=text]").focus();
  } else if (focusId && document.getElementById(focusId)) {
    document.getElementById(focusId).focus();
  } else if (entryId) {
    focusEntry(entryId);
  }
});

// --- Dialogs -------------------------------------------------------------------

function openMove(li) {
  const d = $("#move-dialog");
  const form = d.querySelector("form");
  form.action = `/entries/${li.dataset.id}/move`;
  form.dataset.entry = li.dataset.id;
  form.reset();
  d.querySelector('[data-fill="text"]').textContent = `“${li.dataset.text}”`;
  d.querySelector('[data-fill="forward"]').textContent = li.dataset.forward ? `(${li.dataset.forward})` : "";
  d.showModal();
  d.querySelector("input[name=to]:checked").focus();
}

function openEdit(li) {
  const d = $("#edit-dialog");
  const form = d.querySelector("form");
  form.action = `/entries/${li.dataset.id}/edit`;
  form.dataset.entry = li.dataset.id;
  const input = form.querySelector("input[name=text]");
  input.value = li.dataset.text;
  d.showModal();
  input.select();
}

// Picking a date or week selects its option.
document.addEventListener("input", (ev) => {
  const pick = ev.target.dataset?.pick;
  if (pick) ev.target.closest("label").querySelector("input[name=to]").checked = true;
});

document.addEventListener("click", (ev) => {
  const t = ev.target;
  if (t.closest("[data-close]")) return t.closest("dialog").close();
  if (t.closest("[data-keys]")) return $("#keys-dialog").showModal();
  const act = t.closest("[data-act]");
  if (act) {
    const li = act.closest("li.entry");
    return act.dataset.act === "move" ? openMove(li) : openEdit(li);
  }
  if (t.closest("[data-menu]")) {
    const nav = $("#nav");
    const open = !nav.classList.contains("open");
    nav.classList.toggle("open", open);
    $(".menu-toggle")?.setAttribute("aria-expanded", String(open));
  }
});

// --- Keyboard ------------------------------------------------------------------

const entries = () => $$("#content li.entry");
const current = () => document.activeElement?.closest?.("li.entry");
const typing = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

function step(by) {
  const all = entries();
  if (!all.length) return;
  const i = all.indexOf(current());
  const next = all[i < 0 ? (by > 0 ? 0 : all.length - 1) : Math.min(all.length - 1, Math.max(0, i + by))];
  next.focus();
  next.scrollIntoView({ block: "nearest" });
}

function action(li, path) {
  const data = new FormData();
  data.set("next", location.pathname);
  post(`/entries/${li.dataset.id}/${path}`, data).then((ok) => ok && focusEntry(li.dataset.id));
}

function go(sel) {
  const a = $(sel);
  if (a) location.href = a.href;
}

document.addEventListener("keydown", (ev) => {
  if (ev.ctrlKey || ev.metaKey || ev.altKey || $("dialog[open]")) return;
  if (typing(ev.target)) {
    if (ev.key === "Escape") ev.target.blur();
    return;
  }
  const li = current();
  const task = li?.dataset.kind === "task";
  const state = li?.dataset.state;
  const keys = {
    n: () => {
      const box = $("[data-composer] input[name=text]");
      if (box) box.focus();
      else location.href = "/today#add";
    },
    j: () => step(1),
    k: () => step(-1),
    x: () => task && (state === "open" || state === "done") && action(li, state === "open" ? "done" : "reopen"),
    " ": () => task && (state === "open" || state === "done") && action(li, state === "open" ? "done" : "reopen"),
    c: () => task && (state === "open" || state === "cancelled") && action(li, state === "open" ? "cancel" : "reopen"),
    ">": () => task && state === "open" && action(li, "forward"),
    m: () => task && state === "open" && openMove(li),
    "<": () => task && state === "open" && openMove(li),
    e: () => li && state !== "migrated" && state !== "scheduled" && openEdit(li),
    "[": () => go("a[rel=prev]"),
    "]": () => go("a[rel=next]"),
    t: () => go("[data-go=t]"),
    w: () => go("[data-go=w]"),
    f: () => go("[data-go=f]"),
    v: () => go("a[data-toggle-view]"),
    "?": () => $("#keys-dialog").showModal(),
  };
  const fn = keys[ev.key];
  // Space on a focused button or link keeps its normal meaning (the tick box ticks itself)
  if (!fn || (ev.key === " " && (!li || ev.target.closest("button, a")))) return;
  ev.preventDefault();
  fn();
});

// Arriving from "n" on a page without an add box
if (location.hash === "#add") {
  $("[data-composer] input[name=text]")?.focus();
  history.replaceState(null, "", location.pathname);
}

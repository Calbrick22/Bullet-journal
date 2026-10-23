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
  // The sidebar shows bookmarks and today's date, so redraw it too (keeping the phone menu's state).
  const freshNav = doc.getElementById("nav");
  if (freshNav) $("#nav").innerHTML = freshNav.innerHTML;
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
  await saveNote();   // never lose typing when the page is redrawn
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
  } else if (form.dataset.meeting) {
    $(`[data-meeting="${CSS.escape(form.dataset.meeting)}"]`)?.focus();
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
  // Only offer moves that make sense from where the task is now.
  const where = li.dataset.where;
  const onToday = li.dataset.date && li.dataset.date === document.body.dataset.today;
  const show = {
    "not-today": !onToday,
    "not-ongoing": where !== "ongoing",
    "not-backlog": where !== "backlog",
    dated: where === "day" || where === "week",
  };
  for (const label of $$("[data-show]", d)) label.hidden = !show[label.dataset.show];
  const first = $$("input[name=to]", d).find((r) => !r.closest("label").hidden);
  first.checked = true;
  d.showModal();
  first.focus();
}

function openCategory(el) {
  const d = $("#category-dialog");
  const form = d.querySelector("form");
  form.action = `/meetings/${encodeURIComponent(el.dataset.meeting)}/category`;
  delete form.dataset.entry;
  form.dataset.meeting = el.dataset.meeting;
  d.querySelector('[data-fill="subject"]').textContent = `“${el.dataset.subject}”`;
  const radios = $$("input[name=category]", d);
  for (const r of radios) r.checked = r.value === (el.dataset.cat || "");
  const only = d.querySelector("input[name=only_this]");
  if (only) only.checked = false;
  d.showModal();
  (radios.find((r) => r.checked) || radios[0] || d.querySelector("[data-close]")).focus();
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

// Picking a date or week selects its option; picking a colour updates its swatch.
document.addEventListener("input", (ev) => {
  const pick = ev.target.dataset?.pick;
  if (pick) ev.target.closest("label").querySelector("input[name=to]").checked = true;
  if (ev.target.matches("[data-colour]")) {
    const sw = ev.target.closest("form").querySelector("[data-swatch]");
    sw.className = `swatch cat-${ev.target.value}`;
  }
});

document.addEventListener("click", (ev) => {
  const t = ev.target;
  if (t.closest("[data-close]")) return t.closest("dialog").close();
  if (t.closest("[data-keys]")) return $("#keys-dialog").showModal();
  const mtg = t.closest("[data-meeting]");
  if (mtg && !t.closest("dialog")) return openCategory(mtg);
  const act = t.closest("[data-act]");
  if (act) {
    const li = act.closest("li.entry") || $(".note-head");
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
    e: () => (li ? state !== "migrated" && state !== "scheduled" && openEdit(li) : $(".note-head") && openEdit($(".note-head"))),
    o: () => go("[data-go=o]"),
    "[": () => go("a[rel=prev]"),
    "]": () => go("a[rel=next]"),
    t: () => go("[data-go=t]"),
    w: () => go("[data-go=w]"),
    f: () => go("[data-go=f]"),
    b: () => go("[data-go=b]"),
    s: () => go("[data-go=s]"),
    v: () => go("a[data-toggle-view]"),
    "?": () => $("#keys-dialog").showModal(),
  };
  const mtg = ev.target.closest?.("[data-meeting]");
  if (mtg && (ev.key === "Enter" || ev.key === " ")) {
    ev.preventDefault();
    return openCategory(mtg);
  }
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

// --- Note editor -----------------------------------------------------------------
// The details of a note: contenteditable with bold, italic, underline and lists.
// Saves a moment after typing stops, on leaving the box, and before the page goes.
// The server keeps only those few tags (notes.sanitise), whatever arrives.

const SAVE_DELAY = 800;
let saveTimer = null;

const noteBody = () => $("#note-body");

async function saveNote() {
  const box = noteBody();
  clearTimeout(saveTimer);
  if (!box || box.dataset.dirty !== "1") return;
  box.dataset.dirty = "0";
  const stamp = $("[data-stamp]");
  const data = new FormData();
  data.set("body", box.innerHTML);
  try {
    const res = await fetch(box.dataset.save, { method: "POST", body: data });
    if (!res.ok) throw new Error(await res.text());
    if (stamp) stamp.textContent = await res.text();
  } catch {
    box.dataset.dirty = "1";
    if (stamp) stamp.textContent = "Not saved yet, retrying…";
    saveTimer = setTimeout(saveNote, 3000);
  }
}

function noteChanged() {
  const box = noteBody();
  box.dataset.dirty = "1";
  const stamp = $("[data-stamp]");
  if (stamp) stamp.textContent = "Saving…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNote, SAVE_DELAY);
}

function toolbarState() {
  for (const b of $$(".note-toolbar [data-cmd]")) {
    let on = false;
    try { on = document.queryCommandState(b.dataset.cmd); } catch {}
    b.setAttribute("aria-pressed", String(on));
  }
}

function format(cmd) {
  const box = noteBody();
  if (!box) return;
  if (document.activeElement !== box) box.focus();
  document.execCommand(cmd);
  toolbarState();
  noteChanged();
}

try {
  document.execCommand("styleWithCSS", false, false);           // <b>, not <span style>
  document.execCommand("defaultParagraphSeparator", false, "p");
} catch {}

// Keep the selection in the text when a toolbar button is pressed
document.addEventListener("mousedown", (ev) => {
  if (ev.target.closest(".note-toolbar [data-cmd]")) ev.preventDefault();
});
document.addEventListener("click", (ev) => {
  const b = ev.target.closest(".note-toolbar [data-cmd]");
  if (b) format(b.dataset.cmd);
});
document.addEventListener("input", (ev) => {
  if (ev.target.id === "note-body") noteChanged();
});
document.addEventListener("focusout", (ev) => {
  if (ev.target.id === "note-body") saveNote();
});
document.addEventListener("selectionchange", () => {
  if (document.activeElement?.id === "note-body") toolbarState();
});
document.addEventListener("keydown", (ev) => {
  if (ev.target.id !== "note-body" || !(ev.ctrlKey || ev.metaKey) || !ev.shiftKey) return;
  if (ev.code === "Digit8") { ev.preventDefault(); format("insertUnorderedList"); }
  if (ev.code === "Digit7") { ev.preventDefault(); format("insertOrderedList"); }
});
// Paste as plain text: no fonts or colours from Outlook or Word
document.addEventListener("paste", (ev) => {
  if (ev.target.closest?.("#note-body")) {
    ev.preventDefault();
    document.execCommand("insertText", false, ev.clipboardData.getData("text/plain"));
  }
});
// Leaving the page with unsaved typing: send it on the way out
window.addEventListener("pagehide", () => {
  const box = noteBody();
  if (box && box.dataset.dirty === "1") {
    const data = new FormData();
    data.set("body", box.innerHTML);
    navigator.sendBeacon(box.dataset.save, data);
  }
});
// A select that saves as soon as it changes (the note's category)
document.addEventListener("change", (ev) => {
  const form = ev.target.closest("form[data-autosubmit]");
  if (form) form.requestSubmit();
});

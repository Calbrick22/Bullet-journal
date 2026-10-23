// Small progressive enhancement. Without it every form still works by
// posting and redirecting; with it, posts update the page in place and keep focus.

document.addEventListener("submit", async (ev) => {
  const form = ev.target.closest("form[data-inline]");
  if (!form) return;
  ev.preventDefault();
  const focusId = document.activeElement?.id;
  const composer = form.hasAttribute("data-composer");
  const kind = form.querySelector("input[name=kind]:checked")?.value;
  const target = form.querySelector("select[name=target]")?.value;

  let res;
  try {
    res = await fetch(form.action, { method: "POST", body: new FormData(form) });
  } catch {
    return form.submit();
  }
  if (!res.ok) return form.submit();
  const doc = new DOMParser().parseFromString(await res.text(), "text/html");
  const fresh = doc.getElementById("content");
  if (!fresh) return location.reload();
  document.getElementById("content").replaceWith(fresh);
  document.title = doc.title;

  if (composer) {
    // Keep adding: same kind, same day, cursor back in the box.
    const f = document.querySelector("[data-composer]");
    if (kind) f.querySelector(`input[name=kind][value="${kind}"]`).checked = true;
    const sel = f.querySelector("select[name=target]");
    if (sel && target) sel.value = target;
    f.querySelector("input[name=text]").focus();
  } else if (focusId) {
    document.getElementById(focusId)?.focus();
  }
});

// Phone menu
document.addEventListener("click", (ev) => {
  if (!ev.target.closest("[data-menu]")) return;
  const nav = document.getElementById("nav");
  const open = !nav.classList.contains("open");
  nav.classList.toggle("open", open);
  document.querySelector(".menu-toggle")?.setAttribute("aria-expanded", String(open));
});

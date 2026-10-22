// Renders the weekly-spread mock from SAMPLE. Throwaway: milestone 3 renders
// the same markup server-side with Jinja.
(() => {
  const { week, ahead, facts, synced } = window.SAMPLE;
  const SIG = { "task:open": "•", "task:done": "×", "task:migrated": ">", "task:scheduled": "<",
                "task:cancelled": "•", "event:open": "○", "note:open": "–" };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const $ = (sel) => document.querySelector(sel);
  const ordinal = (n) => n + ({ 1: "st", 2: "nd", 3: "rd" }[n % 100 > 10 && n % 100 < 14 ? 0 : n % 10] || "th");
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  const entry = (e, { showTrail = true } = {}) => {
    const sig = SIG[`${e.kind}:${e.state}`];
    let after = "";
    if (e.state === "migrated") after = `<span class="moved">to ${esc(e.to)}</span>`;
    if (e.trail && showTrail) after = `<span class="pill warn">${ordinal(e.trail.length)} day</span>`;
    if (e.scheduledFrom) after = `<span class="moved">planned on ${esc(e.scheduledFrom)}</span>`;
    return `<li class="entry ${e.kind} ${e.state}${e.trail ? " carried" : ""}">
      <span class="sig" aria-label="${e.kind}, ${e.state}">${sig}</span>
      <span class="text">${esc(e.text)}${after ? " " + after : ""}</span></li>`;
  };

  const meeting = (m) => `<li class="meeting">
      <span class="time num">${m.start}–${m.end}</span>
      <span class="subject">${esc(m.subject)}</span></li>`;

  const today = week.days.find((d) => d.date === week.today);
  const weekday = new Date(week.today + "T12:00:00").toLocaleDateString("en-GB", { weekday: "long" });
  const longDate = new Date(week.today + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long" });

  $("[data-greeting]").textContent = `${weekday}, week ${week.number}`;
  $("[data-facts]").textContent =
    `${longDate} · ${plural(facts.meetingsToday, "meeting")}, the first at ${facts.firstMeeting} · ` +
    `${plural(facts.carriedToday, "task")} came over, one on its ${ordinal(facts.longestCarry)} day`;
  $("[data-synced]").textContent = synced;

  const day = (d) => {
    const isToday = d.date === week.today;
    const isPast = d.date < week.today;
    const open = d.entries.filter((e) => e.kind === "task" && e.state === "open").length;
    return `<article class="day${isToday ? " today" : ""}${isPast ? " past" : ""}" aria-label="${d.label}${isToday ? ", today" : ""}">
      <header><h2>${d.label}</h2>${isToday ? '<span class="today-label">Today</span>' : `<span class="meta num">${isPast ? "" : plural(open, "task")}</span>`}</header>
      ${d.meetings.length ? `<ul class="meetings" aria-label="Meetings">${d.meetings.map(meeting).join("")}</ul>` : ""}
      <ul class="entries">${d.entries.map((e) => entry(e)).join("")}</ul>
    </article>`;
  };

  $("[data-spread]").innerHTML = week.days.map(day).join("") +
    `<article class="day unplaced" aria-label="This week, no day yet">
      <header><h2>No day yet</h2><span class="meta num">${plural(week.unplaced.length, "task")}</span></header>
      <ul class="entries">${week.unplaced.map((e) => entry(e)).join("")}</ul>
    </article>`;

  // Capped to match Rolling over, so the two panels end level; the rest is in the future log.
  const AHEAD_ROWS = 4;
  $("[data-ahead]").innerHTML = ahead.slice(0, AHEAD_ROWS).map((a) => `<li class="row ahead-row">
      <span class="when num">${esc(a.when)}</span>${a.off
        ? `<span class="off-what">${esc(a.off)}</span><span class="pill">${plural(a.days, "day")} off</span>`
        : entry(a.entry).replace(/^<li/, "<span").replace(/<\/li>$/, "</span>")}</li>`).join("");
  $("[data-ahead-more]").textContent = `${ahead.length - AHEAD_ROWS} more in the future log`;

  const carried = today.entries.filter((e) => e.trail).sort((a, b) => b.trail.length - a.trail.length);
  $("[data-rolling-count]").textContent = plural(carried.length, "task");
  $("[data-rolling]").innerHTML = carried.map((e) => `<li class="row roll-row">
      <div class="roll-main"><span class="roll-text">${esc(e.text)}</span>
        <span class="trail">${e.trail.map(esc).join(" › ")}</span></div>
      <button class="card-link plain" type="button">Schedule</button></li>`).join("");


  // Phone menu
  document.querySelectorAll("[data-menu]").forEach((b) => b.addEventListener("click", () => {
    const nav = $("#nav"), open = !nav.classList.contains("open");
    nav.classList.toggle("open", open);
    $(".menu-toggle").setAttribute("aria-expanded", String(open));
  }));
  // Segmented kind picker
  document.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => {
    b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
})();

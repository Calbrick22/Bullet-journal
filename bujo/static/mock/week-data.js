// Sample data for the static weekly-spread mock (milestone 2).
// Shaped like what bujo.journal returns; replaced by the real database in milestone 3.
// Today is Thursday 22 October 2026, 08:52 Europe/London. All names are sample data.

window.SAMPLE = (() => {
  const t = (text, state = "open", extra = {}) => ({ kind: "task", text, state, ...extra });
  const note = (text) => ({ kind: "note", text, state: "open" });
  const event = (text) => ({ kind: "event", text, state: "open" });
  const m = (start, end, subject, where = "") => ({ start, end, subject, where });

  const week = {
    key: "2026-W43",
    number: 43,
    today: "2026-10-22",
    days: [
      { date: "2026-10-19", label: "Mon 19",
        meetings: [m("09:30", "10:00", "Weekly ops stand-up", "Teams"), m("14:00", "15:00", "Q4 planning", "Room 3.12")],
        entries: [
          t("Draft agenda for Thursday's review", "done"),
          t("Send Q3 figures to Priya", "migrated", { to: "Tue" }),
          t("Book train to Leeds for 3 Nov", "done"),
          note("Ops review moved to Thursday"),
        ] },
      { date: "2026-10-20", label: "Tue 20",
        meetings: [m("10:00", "10:30", "1:1 with Hannah"), m("13:00", "14:00", "Supplier call: Brightline", "Teams"), m("16:00", "16:30", "Budget check-in")],
        entries: [
          t("Send Q3 figures to Priya", "migrated", { to: "Wed" }),
          t("Reply to Hannah about the supplier contract", "done"),
          t("Review Dev's onboarding checklist", "migrated", { to: "Wed" }),
          t("Order a new laptop charger", "cancelled"),
        ] },
      { date: "2026-10-21", label: "Wed 21",
        meetings: [m("09:30", "10:00", "Weekly ops stand-up", "Teams"), m("11:30", "12:30", "Vendor demo: Fieldline"), m("15:00", "15:30", "Hiring sync")],
        entries: [
          t("Send Q3 figures to Priya", "migrated", { to: "Thu" }),
          t("Review Dev's onboarding checklist", "migrated", { to: "Thu" }),
          t("Update the risk register", "done"),
          t("Chase IT about the VPN token", "migrated", { to: "Thu" }),
          event("Fire drill at 11:00"),
          note("Priya wants the regional split, not just totals"),
        ] },
      { date: "2026-10-22", label: "Thu 22",
        meetings: [m("09:30", "10:00", "Weekly ops stand-up", "Teams"), m("11:00", "12:00", "Ops review", "Room 3.12"), m("14:00", "14:30", "1:1 with Sam"), m("16:30", "17:00", "Quarterly numbers with Priya")],
        entries: [
          t("Send Q3 figures to Priya", "open", { trail: ["Mon", "Tue", "Wed", "Thu"] }),
          t("Review Dev's onboarding checklist", "open", { trail: ["Tue", "Wed", "Thu"] }),
          t("Chase IT about the VPN token", "open", { trail: ["Wed", "Thu"] }),
          t("Approve October timesheets", "done"),
          t("Prepare slides for the ops review"),
          t("Book a room for the team lunch"),
          note("Ask about Q1 headcount"),
        ] },
      { date: "2026-10-23", label: "Fri 23",
        meetings: [m("09:30", "10:00", "Weekly ops stand-up", "Teams")],
        entries: [
          t("Submit September expenses", "open", { scheduledFrom: "9 Oct" }),
          event("Team lunch, 12:30"),
          t("Send the ops review minutes"),
        ] },
    ],
    unplaced: [t("Clear out the shared drive folder"), t("Read the new travel policy")],
  };

  // Forward-looking, in date order: scheduled entries, week-only entries (dated by the week's Monday)
  // and days off. `on` is the sort key.
  const ahead = [
    { on: "2026-10-26", when: "Mon 26 Oct", entry: t("Plan the November rota") },
    { on: "2026-11-02", when: "Week 45", entry: t("Start the Q1 headcount plan") },
    { on: "2026-11-03", when: "Tue 3 Nov", entry: event("Leeds site visit") },
    { on: "2026-11-05", when: "Thu 5 Nov", entry: t("Book the dentist") },
    { on: "2026-11-09", when: "9–11 Nov", off: "Annual leave", days: 3 },
    { on: "2026-11-09", when: "Week 46", entry: t("Renew the parking permit") },
    { on: "2026-12-25", when: "Fri 25 Dec", off: "Christmas Day", days: 1 },
  ];
  for (let i = 1; i < ahead.length; i++) console.assert(ahead[i - 1].on <= ahead[i].on, "ahead out of order", ahead[i]);

  // Derived figures: computed here, never typed into the markup.
  const today = week.days.find((d) => d.date === week.today);
  const tasks = (es) => es.filter((e) => e.kind === "task");
  const carried = tasks(today.entries).filter((e) => e.trail);
  const facts = {
    meetingsToday: today.meetings.length,
    firstMeeting: today.meetings[0]?.start ?? null,
    openToday: tasks(today.entries).filter((e) => e.state === "open").length,
    carriedToday: carried.length,
    longestCarry: Math.max(0, ...carried.map((e) => e.trail.length)),
    longestCarryText: carried.reduce((a, e) => (e.trail.length > (a?.trail.length ?? 0) ? e : a), null)?.text,
  };

  // Every migrated entry in the week has an open or migrated copy on the day it went to.
  const byLabel = Object.fromEntries(week.days.map((d) => [d.label.slice(0, 3), d]));
  for (const d of week.days) {
    for (const e of d.entries.filter((x) => x.state === "migrated")) {
      console.assert(byLabel[e.to]?.entries.some((x) => x.text === e.text), "migrated copy missing", e);
    }
  }
  // A trail ends today and has one step per carry.
  for (const e of carried) console.assert(e.trail.at(-1) === today.label.slice(0, 3), "trail must end today", e);
  console.assert(facts.openToday === 5 && facts.carriedToday === 3 && facts.longestCarry === 4, "facts", facts);

  return { week, ahead, facts, synced: "08:45" };
})();

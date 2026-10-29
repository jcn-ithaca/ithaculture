const VENUE_COLORS = {
  "Bike Bar": "--v-bikebar",
  "Liquid State Brewing": "--v-liquid",
  "K-HOUSE": "--v-khouse",
  "Cinemapolis": "--v-cinema",
  "Hangar Theatre": "--v-hangar",
  "State Theatre": "--v-state",
  "Visit Ithaca": "--v-visit",
  "Trees Up Tompkins": "--v-trees",
  "Ithaca Children's Garden": "--v-icg",
  "Brewer's Kitchen & Taproom": "--v-brewers",
  "Table for One Trivia": "--v-t41",
  "Misc": "--v-muse",
};
const TZ = "America/New_York";
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const weekday = (d) => d.toLocaleDateString("en-US", { timeZone: TZ, weekday: "short" });
const dayKey = (d) => d.toLocaleDateString("en-CA", { timeZone: TZ });
const dayLabel = (d) =>
  d.toLocaleDateString("en-US", { timeZone: TZ, weekday: "long", month: "long", day: "numeric" });
const timeLabel = (d) =>
  d.toLocaleTimeString("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" }).replace(":00", "");

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style") node.style.cssText = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

function venueStyle(name) {
  const v = VENUE_COLORS[name];
  return v ? `--venue: var(${v})` : "";
}

// Filter choices are remembered per browser. We store what the visitor hid,
// so a newly added venue shows up by default.
const STORE_KEY = "ithaculture.filters";

function loadHidden() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
    return { venues: saved.venues || [], days: saved.days || [] };
  } catch {
    return { venues: [], days: [] };
  }
}

function saveHidden() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      venues: data.venues.map((v) => v.name).filter((n) => !active.has(n)),
      days: WEEKDAYS.filter((d) => !activeDays.has(d)),
    }));
  } catch {
    // Storage blocked (private mode etc.): filters still work for this visit.
  }
}

let data = null;
let active = new Set();
let activeDays = new Set(WEEKDAYS);

function render() {
  const main = document.getElementById("agenda");
  main.replaceChildren();
  const events = data.events.filter((e) => active.has(e.venue) && activeDays.has(weekday(new Date(e.start))));
  if (!events.length) {
    main.append(el("p", { class: "empty" }, "No upcoming events for the selected venues and days."));
    return;
  }
  const days = new Map();
  for (const e of events) {
    const start = new Date(e.start);
    const key = dayKey(start);
    if (!days.has(key)) days.set(key, { date: start, items: [] });
    days.get(key).items.push({ ...e, startDate: start });
  }
  for (const { date, items } of days.values()) {
    const wd = weekday(date);
    const section = el("section", { class: "day" + (["Fri", "Sat", "Sun"].includes(wd) ? " weekend" : "") },
      el("h2", {}, dayLabel(date)));
    // Films are grouped into one card per title so a day isn't swamped by showtimes.
    const films = new Map();
    for (const e of items) {
      if (e.kind === "film") {
        if (!films.has(e.title)) films.set(e.title, []);
        films.get(e.title).push(e);
        continue;
      }
      section.append(eventCard(e));
    }
    if (films.size) section.append(filmCard(films));
    main.append(section);
  }
  addMoreToggles();
}

function venueLink(name) {
  const v = data.venues.find((x) => x.name === name);
  return v && v.url
    ? el("a", { class: "venue", href: v.url, target: "_blank", rel: "noopener" }, name)
    : el("span", { class: "venue" }, name);
}

function eventCard(e) {
  const title = e.url ? el("a", { href: e.url, target: "_blank", rel: "noopener" }, e.title) : e.title;
  return el("article", { class: "ev", style: venueStyle(e.venue) },
    el("div", { class: "time" }, e.all_day ? "All day" : timeLabel(e.startDate)),
    el("div", { class: "title" }, title),
    el("div", { class: "meta" },
      venueLink(e.venue),
      e.description && e.description.length <= SHORT_DESC ? ` · ${e.description}` : null),
    e.description && e.description.length > SHORT_DESC
      ? el("div", { class: "desc clamp" }, el("span", { class: "desc-text" }, e.description))
      : null);
}

// Short descriptions ("at South Hill Cider") stay on the venue line. Longer
// ones get their own line, clipped to two lines, with a "More" toggle that
// appears only when the text actually overflows at the current width.
const SHORT_DESC = 60;

function addMoreToggles() {
  for (const box of document.querySelectorAll(".desc.clamp")) {
    const text = box.querySelector(".desc-text");
    let btn = box.querySelector(".more");
    const overflows = box.classList.contains("open") || text.scrollHeight > text.clientHeight + 1;
    if (!overflows) { btn?.remove(); continue; }
    if (btn) continue;
    btn = el("button", { type: "button", class: "more", "aria-expanded": "false" }, "More ›");
    btn.addEventListener("click", () => {
      const open = box.classList.toggle("open");
      btn.textContent = open ? "Less ‹" : "More ›";
      btn.setAttribute("aria-expanded", String(open));
    });
    box.append(btn);
  }
}
let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(addMoreToggles, 150); });

// One collapsible line per day: the summary counts films and showtimes,
// and opening it lists each film with its times (each links to tickets).
function filmCard(films) {
  const list = el("div", { class: "films" });
  let count = 0;
  for (const [title, shows] of films) {
    const times = el("span", { class: "times" });
    shows.forEach((s, i) => {
      if (i) times.append(", ");
      times.append(s.url
        ? el("a", { href: s.url, target: "_blank", rel: "noopener" }, timeLabel(s.startDate))
        : timeLabel(s.startDate));
      count++;
    });
    list.append(el("div", { class: "film" }, el("span", { class: "title" }, title), " ", times));
  }
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  return el("details", { class: "ev filmday", style: venueStyle("Cinemapolis") },
    el("summary", {},
      el("span", { class: "time" }, "Films"),
      el("span", { class: "title" }, plural(films.size, "film"), " · ", plural(count, "showtime")),
      el("span", { class: "meta" },
        el("a", { class: "venue", href: "https://www.cinemapolis.org/now-showing", target: "_blank", rel: "noopener" }, "Cinemapolis"))),
    list);
}

// Each filter is a dropdown of checkboxes. Its summary says what's showing.
function menuState(selected, all, label) {
  if (selected.length === all.length) return "All";
  if (!selected.length) return "None";
  return selected.length <= 2 ? selected.map(label).join(", ") : `${selected.length} of ${all.length}`;
}

function buildMenu(menuId, items, chosen, label, extra = {}) {
  const menu = document.getElementById(menuId);
  const list = menu.querySelector(".menu-list");
  const state = menu.querySelector(".menu-state");
  const sync = () => {
    state.textContent = menuState(items.filter((i) => chosen.has(i)), items, label);
    list.querySelectorAll("input").forEach((box) => { box.checked = chosen.has(box.value); });
    saveHidden();
    render();
  };
  list.replaceChildren();
  for (const item of items) {
    const box = el("input", { type: "checkbox", value: item });
    box.addEventListener("change", () => {
      box.checked ? chosen.add(item) : chosen.delete(item);
      sync();
    });
    list.append(el("label", { style: extra.style ? extra.style(item) : "" }, box, " ", label(item)));
  }
  const bulk = (sel, pick) => {
    const btn = menu.querySelector(sel);
    if (btn) btn.onclick = () => { chosen.clear(); items.filter(pick).forEach((i) => chosen.add(i)); sync(); };
  };
  bulk("[data-all]", () => true);
  bulk("[data-none]", () => false);
  bulk("[data-weekend]", (d) => ["Fri", "Sat", "Sun"].includes(d));
  state.textContent = menuState(items.filter((i) => chosen.has(i)), items, label);
  list.querySelectorAll("input").forEach((box) => { box.checked = chosen.has(box.value); });
}

function renderFilters() {
  buildMenu("venue-menu", data.venues.map((v) => v.name), active, (n) => n, { style: venueStyle });
}

function renderDayFilters() {
  buildMenu("day-menu", WEEKDAYS, activeDays, (d) => d);
}

// Close an open menu when clicking elsewhere or pressing Escape; one open at a time.
document.addEventListener("click", (e) => {
  document.querySelectorAll("details.menu[open]").forEach((m) => { if (!m.contains(e.target)) m.open = false; });
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.querySelectorAll("details.menu[open]").forEach((m) => { m.open = false; });
});

function renderMeta() {
  const updated = new Date(data.generated_at);
  document.getElementById("updated").textContent =
    "Updated " + updated.toLocaleString("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const sources = document.getElementById("sources");
  sources.append("Sources: ");
  data.venues.forEach((v, i) => {
    if (i) sources.append(" · ");
    sources.append(v.url ? el("a", { href: v.url, target: "_blank", rel: "noopener" }, v.name) : v.name);
    if (!v.ok) sources.append(el("span", { class: "warn" }, " (couldn't be read today)"));
  });
}

fetch("events.json", { cache: "no-cache" })
  .then((r) => r.json())
  .then((json) => {
    data = json;
    const hidden = loadHidden();
    active = new Set(data.venues.map((v) => v.name).filter((n) => !hidden.venues.includes(n)));
    activeDays = new Set(WEEKDAYS.filter((d) => !hidden.days.includes(d)));
    renderFilters();
    renderDayFilters();
    renderMeta();
    render();
  })
  .catch(() => {
    document.getElementById("agenda").replaceChildren(
      el("p", { class: "empty" }, "Couldn't load the event list. Try again later."));
  });

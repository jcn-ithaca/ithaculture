const VENUE_COLORS = {
  "Bike Bar": "--v-bikebar",
  "Liquid State Brewing": "--v-liquid",
  "K-HOUSE": "--v-khouse",
  "Cinemapolis": "--v-cinema",
  "Hangar Theatre": "--v-hangar",
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
}

function eventCard(e) {
  const title = e.url ? el("a", { href: e.url, target: "_blank", rel: "noopener" }, e.title) : e.title;
  return el("article", { class: "ev", style: venueStyle(e.venue) },
    el("div", { class: "time" }, e.all_day ? "All day" : timeLabel(e.startDate)),
    el("div", { class: "title" }, title),
    el("div", { class: "meta" },
      el("span", { class: "venue" }, e.venue),
      e.description ? ` · ${e.description}` : null));
}

function filmCard(films) {
  const list = el("div", { class: "films" });
  for (const [title, shows] of films) {
    const times = shows.map((s) => timeLabel(s.startDate)).join(", ");
    list.append(el("div", {}, el("span", { class: "title" }, title), " ",
      el("span", { class: "times" }, times)));
  }
  return el("article", { class: "ev", style: venueStyle("Cinemapolis") },
    el("div", { class: "time" }, "Films"),
    list,
    el("div", { class: "meta" },
      el("a", { class: "venue", href: "https://www.cinemapolis.org/now-showing", target: "_blank", rel: "noopener" }, "Cinemapolis"),
      " · today's showtimes"));
}

function renderFilters() {
  const nav = document.getElementById("filters");
  nav.replaceChildren();
  for (const v of data.venues) {
    const btn = el("button", { type: "button", "aria-pressed": String(active.has(v.name)), style: venueStyle(v.name) }, v.name);
    btn.addEventListener("click", () => {
      active.has(v.name) ? active.delete(v.name) : active.add(v.name);
      renderFilters();
      render();
    });
    nav.append(btn);
  }
}

function renderDayFilters() {
  const nav = document.getElementById("day-filters");
  if (!nav) return;
  nav.replaceChildren();
  for (const d of WEEKDAYS) {
    const btn = el("button", { type: "button", "aria-pressed": String(activeDays.has(d)) }, d);
    btn.addEventListener("click", () => {
      activeDays.has(d) ? activeDays.delete(d) : activeDays.add(d);
      renderDayFilters();
      render();
    });
    nav.append(btn);
  }
}

function renderMeta() {
  const updated = new Date(data.generated_at);
  document.getElementById("updated").textContent =
    "Updated " + updated.toLocaleString("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const sources = document.getElementById("sources");
  sources.append("Sources: ");
  data.venues.forEach((v, i) => {
    if (i) sources.append(" · ");
    sources.append(el("a", { href: v.url, target: "_blank", rel: "noopener" }, v.name));
    if (!v.ok) sources.append(el("span", { class: "warn" }, " (couldn't be read today)"));
  });
}

fetch("events.json", { cache: "no-cache" })
  .then((r) => r.json())
  .then((json) => {
    data = json;
    active = new Set(data.venues.map((v) => v.name));
    renderFilters();
    renderDayFilters();
    renderMeta();
    render();
  })
  .catch(() => {
    document.getElementById("agenda").replaceChildren(
      el("p", { class: "empty" }, "Couldn't load the event list. Try again later."));
  });

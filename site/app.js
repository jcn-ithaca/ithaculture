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
  "Hopshire": "--v-hopshire",
  "The Cherry Arts": "--v-cherry",
  "Hands Four Dancers": "--v-h4d",
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
  renderSlides();
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

// Slideshow of coming performers and events, in a right-hand column on wide
// screens. The pictures come from the venues' own event pages (see
// build_slides in the scraper). It follows the venue filter, skips shows that
// are over, and is only built when the column is visible, so phones never
// download the pictures. A slide can also carry a performer's official
// YouTube video (picked by a scheduled task and checked by the scraper): it
// plays muted over the picture while that slide is showing, and is never
// loaded on phones or for visitors who ask for reduced motion.
const WIDE = window.matchMedia("(min-width: 900px)");
const CALM = window.matchMedia("(prefers-reduced-motion: reduce)");
const SLIDE_MS = 8000;
const VIDEO_SLIDE_MS = 30000;
let slideTimer = null;
let slideIndex = 0;
let slideKey = "";

function slideWhen(s) {
  const d = new Date(s.start);
  const day = dayKey(d) === dayKey(new Date()) ? "Today"
    : d.toLocaleDateString("en-US", { timeZone: TZ, weekday: "long", month: "short", day: "numeric" });
  return s.all_day ? day : `${day} · ${timeLabel(d)}`;
}

function currentSlides() {
  const now = Date.now();
  return (data.slides || []).filter((s) => {
    if (!active.has(s.venue)) return false;
    const start = new Date(s.start).getTime();
    return s.all_day ? dayKey(new Date(s.start)) >= dayKey(new Date()) : start + 3 * 3600e3 > now;
  });
}

function showSlide(i) {
  const box = document.getElementById("slideshow");
  const slides = box.querySelectorAll(".slide");
  if (!slides.length) return;
  slideIndex = (i + slides.length) % slides.length;
  slides.forEach((s, n) => {
    s.classList.toggle("on", n === slideIndex);
    s.setAttribute("aria-hidden", String(n !== slideIndex));
    s.querySelectorAll("a, iframe").forEach((a) => { a.tabIndex = n === slideIndex ? 0 : -1; });
    setVideo(s, n === slideIndex);
  });
  box.querySelectorAll(".slide-nav button").forEach((b, n) =>
    b.setAttribute("aria-current", String(n === slideIndex)));
}

// The video player only exists while its slide is showing, so videos don't
// play (or download) in the background.
function setVideo(slide, on) {
  const id = slide.dataset.video;
  if (!id) return;
  const pic = slide.querySelector(".pic");
  const player = pic.querySelector("iframe");
  if (!on || CALM.matches || !WIDE.matches) {
    if (player) player.remove();
    pic.classList.remove("playing");
    return;
  }
  if (player) return;
  pic.classList.add("playing");
  const params = new URLSearchParams({
    autoplay: "1", mute: "1", playsinline: "1", loop: "1", playlist: id,
    controls: "1", rel: "0", modestbranding: "1",
  });
  pic.append(el("iframe", {
    class: "video",
    src: `https://www.youtube-nocookie.com/embed/${id}?${params}`,
    title: slide.dataset.videoTitle,
    allow: "autoplay; encrypted-media; picture-in-picture",
    referrerpolicy: "strict-origin-when-cross-origin",
    allowfullscreen: "",
  }));
}

function startSlides() {
  clearTimeout(slideTimer);
  slideTimer = null;
  const box = document.getElementById("slideshow");
  const slides = box.querySelectorAll(".slide");
  slides.forEach((s, n) => setVideo(s, n === slideIndex && !document.hidden));
  if (CALM.matches || document.hidden || box.matches(":hover, :focus-within")) return;
  if (slides.length < 2) return;
  const wait = slides[slideIndex] && slides[slideIndex].dataset.video ? VIDEO_SLIDE_MS : SLIDE_MS;
  slideTimer = setTimeout(() => { showSlide(slideIndex + 1); startSlides(); }, wait);
}

function renderSlides() {
  const box = document.getElementById("slideshow");
  if (!data || !WIDE.matches) {
    clearTimeout(slideTimer);
    box.querySelectorAll(".slide").forEach((s) => setVideo(s, false));
    box.hidden = true;
    slideKey = "";
    return;
  }
  const list = currentSlides();
  const key = list.map((s) => s.image).join("|");
  if (key === slideKey && !box.hidden) return;
  slideKey = key;
  box.hidden = !list.length;
  const frame = box.querySelector(".slides");
  const nav = box.querySelector(".slide-nav");
  frame.replaceChildren();
  nav.replaceChildren();
  list.forEach((s, i) => {
    const link = (cls, ...kids) => s.url
      ? el("a", { class: cls, href: s.url, target: "_blank", rel: "noopener" }, ...kids)
      : el("span", { class: cls }, ...kids);
    const lazy = i < 2 ? "eager" : "lazy";
    const fig = el("figure", { class: "slide", style: venueStyle(s.venue) },
      link("pic",
        el("img", { class: "fill", src: s.image, alt: "", loading: lazy }),
        el("img", { class: "main", src: s.image, alt: s.title, loading: lazy })),
      el("figcaption", {},
        el("div", { class: "when" }, slideWhen(s)),
        link("title", s.title),
        el("div", { class: "venue" }, s.venue)));
    if (s.video) {
      fig.dataset.video = s.video.id;
      fig.dataset.videoTitle = `${s.video.title || s.title} (video from ${s.video.channel})`;
      fig.querySelector("figcaption").append(el("div", { class: "source" }, `Video: ${s.video.channel} on YouTube`));
    }
    frame.append(fig);
    const dot = el("button", { type: "button", "aria-label": `Show ${s.title}` });
    dot.addEventListener("click", () => { showSlide(i); startSlides(); });
    nav.append(dot);
  });
  nav.hidden = list.length < 2;
  showSlide(0);
  startSlides();
}

{
  const box = document.getElementById("slideshow");
  for (const ev of ["mouseenter", "focusin"]) box.addEventListener(ev, () => { clearTimeout(slideTimer); slideTimer = null; });
  box.addEventListener("mouseleave", startSlides);
  box.addEventListener("focusout", () => setTimeout(startSlides, 0));
  document.addEventListener("visibilitychange", startSlides);
  WIDE.addEventListener("change", renderSlides);
  CALM.addEventListener("change", startSlides);
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

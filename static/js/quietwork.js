// Small touches. Everything here is optional: without JavaScript the pages are
// complete and static. Motion is skipped when the visitor prefers less of it.
(function () {
  var calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Live countdowns. The server decides when the Zoom link works; this only
  // keeps the numbers fresh and reloads once the join window opens.
  function tick(el) {
    var target = new Date(el.dataset.countdown).getTime();
    var opens = el.dataset.opens ? new Date(el.dataset.opens).getTime() : null;
    var now = Date.now();
    if (opens && now >= opens && !el.dataset.reloaded) {
      el.dataset.reloaded = "1";
      window.location.reload();
      return;
    }
    var s = Math.max(Math.floor((target - now) / 1000), 0);
    var parts = { days: Math.floor(s / 86400), hours: Math.floor((s % 86400) / 3600), minutes: Math.floor((s % 3600) / 60) };
    el.querySelectorAll("[data-unit]").forEach(function (n) {
      var value = String(parts[n.dataset.unit]).padStart(2, "0");
      if (n.textContent === value) return;
      n.textContent = value;
      if (!calm) {
        n.classList.remove("tick");
        void n.offsetWidth; // restart the animation
        n.classList.add("tick");
      }
    });
  }

  // The thread on Home draws itself as you scroll down the page.
  function drawThread(svg) {
    var page = svg.parentElement;
    function update() {
      var rect = page.getBoundingClientRect();
      var seen = (window.innerHeight * 0.85 - rect.top) / rect.height;
      var shown = Math.min(Math.max(seen, 0.12), 1);
      svg.style.clipPath = "inset(0 0 " + ((1 - shown) * 100).toFixed(2) + "% 0)";
    }
    var queued = false;
    window.addEventListener("scroll", function () {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () { queued = false; update(); });
    }, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  // Seat bars and the progress thread fill in when they come into view.
  function revealOnView(els) {
    if (!("IntersectionObserver" in window)) {
      els.forEach(function (el) { el.classList.add("in-view"); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in-view"); io.unobserve(e.target); }
      });
    }, { threshold: 0.4 });
    els.forEach(function (el) { io.observe(el); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var clocks = document.querySelectorAll("[data-countdown]");
    clocks.forEach(tick);
    if (clocks.length) setInterval(function () { clocks.forEach(tick); }, 20000);

    if (calm) return;
    document.documentElement.classList.add("motion");
    document.querySelectorAll("[data-draw-thread]").forEach(drawThread);
    revealOnView(document.querySelectorAll(".bar, [data-fill-in]"));
  });
})();

// "19:00 CET · 20:00 for you": show the visitor's own time when it differs
// from Elena's time zone. Without JavaScript nothing is shown.
(function () {
  var ELENA_TZ = "Europe/Berlin";
  var mine;
  try { mine = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { return; }
  if (!mine || mine === ELENA_TZ) return;
  function parts(date, tz) {
    var f = new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", weekday: "short", hour12: false });
    var out = {};
    f.formatToParts(date).forEach(function (p) { out[p.type] = p.value; });
    return out;
  }
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-local-time]").forEach(function (el) {
      var date = new Date(el.dataset.localTime);
      var here = parts(date, mine), there = parts(date, ELENA_TZ);
      var hereTime = here.hour + ":" + here.minute, thereTime = there.hour + ":" + there.minute;
      if (hereTime === thereTime) return;
      el.textContent = " · " + (here.weekday !== there.weekday ? here.weekday + " " : "") + hereTime + " for you";
      el.title = "Your time zone: " + mine;
      el.hidden = false;
    });
  });
})();

// "Your thread": the line draws itself, then the sessions appear along it.
(function () {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-thread-art]").forEach(function (fig) {
      fig.querySelectorAll("path").forEach(function (p) {
        p.style.setProperty("--len", Math.ceil(p.getTotalLength()));
      });
      requestAnimationFrame(function () { requestAnimationFrame(function () { fig.classList.add("drawing"); }); });
    });
  });
})();

// Live countdowns. The server decides when the Zoom link works; this only
// keeps the numbers fresh and reloads once the join window opens.
(function () {
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
      n.textContent = String(parts[n.dataset.unit]).padStart(2, "0");
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    var els = document.querySelectorAll("[data-countdown]");
    els.forEach(tick);
    if (els.length) setInterval(function () { els.forEach(tick); }, 20000);
  });
})();

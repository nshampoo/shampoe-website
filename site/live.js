// Renders /live.json (written every 15 minutes by the live feed Lambda) into the Live page
// and the homepage strip. Every tile starts hidden and only appears when its data exists.
(function () {
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    for (var k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  }
  function show(id) { var e = $(id); if (e) e.hidden = false; return e; }
  function set(id, text) { var e = $(id); if (e) e.textContent = text; }
  function fmt(n) { return Number(n).toLocaleString("en-US"); }

  function ago(iso) {
    var mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + " min ago";
    var hours = Math.round(mins / 60);
    if (hours < 24) return hours + (hours === 1 ? " hour ago" : " hours ago");
    var days = Math.round(hours / 24);
    return days === 1 ? "yesterday" : days + " days ago";
  }
  function day(isoDate, opts) {
    // isoDate is a plain YYYY-MM-DD; build it at local noon so it never shifts a day.
    var p = isoDate.split("-");
    return new Date(+p[0], +p[1] - 1, +p[2], 12).toLocaleDateString("en-US", opts || { weekday: "short", month: "short", day: "numeric" });
  }
  function clock(seconds) {
    var h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
    return h ? h + ":" + String(m).padStart(2, "0") : m + ":" + String(s).padStart(2, "0");
  }

  // Draw [lat, lng] points into an <svg> as one path, fitted to its viewBox.
  function drawRoute(svg, points, opts) {
    if (!svg || !points || points.length < 2) return false;
    var vb = svg.viewBox.baseVal, pad = opts.pad || 10;
    var k = Math.cos((points[0][0] * Math.PI) / 180);
    var xs = points.map(function (p) { return p[1] * k; }), ys = points.map(function (p) { return -p[0]; });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    var scale = Math.min((vb.width - 2 * pad) / (maxX - minX || 1), (vb.height - 2 * pad) / (maxY - minY || 1));
    var ox = (vb.width - (maxX - minX) * scale) / 2, oy = (vb.height - (maxY - minY) * scale) / 2;
    var d = xs.map(function (x, i) {
      return (i ? "L" : "M") + (ox + (x - minX) * scale).toFixed(1) + " " + (oy + (ys[i] - minY) * scale).toFixed(1);
    }).join(" ");
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    path.setAttribute("class", "route");
    svg.appendChild(path);
    if (opts.ends) {
      var first = d.split(" L")[0].slice(1).split(" "), last = d.split(" L").pop().split(" ");
      [[first, "start"], [last, "end"]].forEach(function (pair) {
        var c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("cx", pair[0][0]); c.setAttribute("cy", pair[0][1]); c.setAttribute("r", 6);
        c.setAttribute("class", "route-" + pair[1]);
        svg.appendChild(c);
      });
    }
    return true;
  }

  function cover(img, book) {
    if (!img) return;
    if (book.cover && !/nophoto/.test(book.cover)) { img.src = book.cover; img.alt = "Cover of " + book.title; }
    else img.hidden = true;
  }

  // ---------------------------------------------------------------- tiles shared by both pages

  function renderTinkering(feed) {
    var repo = feed.github && feed.github.repos && feed.github.repos[0];
    if (!repo || !$("tinkering")) return;
    var a = el("a", { href: repo.url }, repo.name);
    $("tinkering-repo").replaceChildren(a);
    set("tinkering-when", " · pushed " + ago(repo.pushed));
    show("tinkering");
  }

  function renderRun(feed) {
    var run = feed.strava && feed.strava.latest_run;
    if (!run || !$("tile-run")) return;
    drawRoute($("run-map"), run.route, { pad: 14, ends: true });
    set("run-miles", run.miles.toFixed(2));
    set("run-pace", run.pace_seconds_per_mile ? clock(run.pace_seconds_per_mile) : "–");
    set("run-time", clock(run.moving_seconds));
    set("run-name", run.name);
    set("run-date", day(run.date, { weekday: "long", month: "short", day: "numeric" }));
    set("run-short", run.miles.toFixed(1) + " mi");
    show("tile-run");
  }

  function renderGame(feed) {
    var game = feed.strava && feed.strava.latest_game;
    if (!game || !$("tile-game")) return;
    drawRoute($("game-map"), game.route, { pad: 12 });
    set("game-title", game.miles.toFixed(1) + " miles of going nowhere");
    set("game-short", game.miles.toFixed(1) + " mi of chaos");
    var bits = [Math.round(game.moving_seconds / 60) + " minutes of flag football"];
    if (game.calories) bits.push(fmt(game.calories) + " calories");
    if (game.max_mph) bits.push("top speed " + game.max_mph + " mph");
    set("game-detail", bits.join(", ") + ". " + day(game.date) + ".");
    set("game-date", "Flag football · " + day(game.date, { month: "short", day: "numeric" }));
    show("tile-game");
  }

  function renderCitibike(feed) {
    var cb = feed.citibike;
    if (!cb || !$("tile-citibike")) return;
    set("cb-undocked", fmt(cb.undocked_today));
    set("cb-empty", fmt(cb.empty_now));
    set("cb-stations", fmt(cb.stations));
    show("tile-citibike");
  }

  function renderBooks(feed) {
    var gr = feed.goodreads;
    if (!gr || !$("tile-books")) return;
    var current = gr.current && gr.current[0], last = gr.recent && gr.recent[0];
    var book = current || last;
    if (!book) return;
    set("book-label", current ? "Currently reading" : "Last finished");
    set("book-title", book.title);
    var by = book.author;
    if (!current && book.rating) by += " · " + book.rating + " of 5";
    if (!current && book.read) by += " · " + day(book.read, { month: "short", day: "numeric" });
    set("book-by", by);
    cover($("book-cover"), book);
    if (gr.total_read) { set("book-total", fmt(gr.total_read)); show("book-total-wrap"); }
    var list = $("book-more");
    if (list) {
      var more = (gr.recent || []).filter(function (b) { return b !== book; }).slice(0, 2);
      more.forEach(function (b) { list.appendChild(el("li", null, b.title + (b.rating ? " · " + b.rating + " of 5" : ""))); });
      if (more.length) list.hidden = false;
    }
    show("tile-books");
  }

  // ---------------------------------------------------------------- Live page only

  function renderRepos(feed) {
    var repos = feed.github && feed.github.repos;
    if (!repos || !repos.length || !$("tile-repos")) return;
    var list = $("repo-list");
    repos.slice(0, 4).forEach(function (r) {
      var li = el("li");
      li.appendChild(el("a", { href: r.url, class: "mono" }, r.name));
      li.appendChild(el("span", null, ago(r.pushed)));
      list.appendChild(li);
    });
    show("tile-repos");
  }

  function renderMonth(feed) {
    var m = feed.strava && feed.strava.month;
    if (!m || !$("tile-month")) return;
    set("month-label", m.label + ", by the numbers");  // e.g. "Last 30 days, by the numbers"
    var rows = [["E-bike rides", m.rides, "ride"], ["Flag football", m.flag_football, "football"], ["Runs", m.runs, "run"], ["Swims", m.swims, "swim"]];
    var max = Math.max.apply(null, rows.map(function (r) { return r[1]; })) || 1;
    var box = $("month-bars");
    rows.forEach(function (r) {
      var row = el("div", { class: "bar-row" });
      row.appendChild(el("span", null, r[0]));
      var track = el("span", { class: "track" });
      var fill = el("span", { class: "fill " + r[2] });
      fill.style.width = (r[1] / max) * 100 + "%";
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("b", null, String(r[1])));
      box.appendChild(row);
    });
    show("tile-month");
  }

  function renderTitle(feed) {
    var t = feed.strava && feed.strava.title_of_the_month;
    if (!t || !$("tile-title")) return;
    set("title-name", "“" + t.name + "”");
    var types = { EBikeRide: "E-bike ride", Ride: "Ride", Run: "Run", Swim: "Swim", Walk: "Walk", Hike: "Hike", Workout: "Workout" };
    set("title-when", (types[t.type] || t.type) + " · " + day(t.date, { month: "short", day: "numeric" }));
    show("tile-title");
  }

  // Volo drop-ins: one stacked bar per day (flag football + other sports = total).
  function renderVolo(feed) {
    var v = feed.volo;
    if (!v || !$("tile-volo")) return;
    show("tile-volo");
    var byDay = {};
    (v.days || []).forEach(function (d) { byDay[d.day] = d; });
    var range = 60;

    function draw() {
      var bars = $("volo-bars"), table = $("volo-table-body");
      bars.replaceChildren(); table.replaceChildren();
      var today = new Date(), days = [];
      for (var i = range - 1; i >= 0; i--) {
        var d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i, 12);
        var key = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
        var row = byDay[key] || { total: 0, football: 0 };
        days.push({ key: key, total: row.total, football: row.football, other: row.total - row.football });
      }
      var max = Math.max(5, Math.max.apply(null, days.map(function (d) { return d.total; })));
      var top = Math.ceil(max / 5) * 5;
      set("volo-y-top", top); set("volo-y-mid", top / 2);
      var football = 0, other = 0;
      days.forEach(function (d) {
        football += d.football; other += d.other;
        var col = el("button", { type: "button", class: "day", "aria-label": day(d.key) + ": " + d.total + " drop-ins, " + d.football + " flag football" });
        if (d.other) { var o = el("span", { class: "seg other" }); o.style.height = (d.other / top) * 100 + "%"; col.appendChild(o); }
        if (d.football) { var f = el("span", { class: "seg football" }); f.style.height = (d.football / top) * 100 + "%"; col.appendChild(f); }
        var tip = el("span", { class: "tip", role: "tooltip" });
        tip.appendChild(el("b", null, day(d.key) + " · " + d.total + " drop-in" + (d.total === 1 ? "" : "s")));
        tip.appendChild(el("span", { class: "t-football" }, d.football + " flag football"));
        tip.appendChild(el("span", { class: "t-other" }, d.other + " other sports"));
        col.appendChild(tip);
        bars.appendChild(col);
        if (d.total) {
          var tr = el("tr");
          tr.appendChild(el("td", null, day(d.key)));
          tr.appendChild(el("td", null, String(d.total)));
          tr.appendChild(el("td", null, String(d.football)));
          table.appendChild(tr);
        }
      });
      set("volo-football", fmt(football));
      set("volo-other", fmt(other));
      set("volo-x-start", range + " days ago");
      set("volo-x-mid", range / 2 + " days ago");
      $("volo-empty").hidden = football + other > 0;
    }

    document.querySelectorAll("[data-range]").forEach(function (b) {
      b.addEventListener("click", function () {
        range = +b.getAttribute("data-range");
        document.querySelectorAll("[data-range]").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        draw();
      });
    });
    set("volo-since", v.counting_since ? "Counting since " + day(v.counting_since, { month: "short", day: "numeric", year: "numeric" }) : "Counting started Oct 2, 2026");
    draw();
  }

  function render(feed) {
    renderTinkering(feed);
    renderRun(feed); renderGame(feed); renderCitibike(feed); renderBooks(feed);
    renderRepos(feed); renderMonth(feed); renderTitle(feed); renderVolo(feed);
    if ($("updated")) { set("updated", "Updated " + ago(feed.updated)); show("updated-wrap"); }
    if ($("live-strip") && document.querySelector("#live-strip .tile:not([hidden])")) show("live-strip");
  }

  fetch("/live.json", { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (feed) {
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { render(feed); });
      else render(feed);
    })
    .catch(function () { /* the page still works without live data */ });
})();

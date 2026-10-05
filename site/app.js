(function () {
  var D = window.FORECAST, root = document.documentElement;
  var state = { loc: 0, days: 120 };
  try { var t = localStorage.getItem("fc-theme"); if (t) root.dataset.theme = t; } catch (e) {}
  var $ = function (id) { return document.getElementById(id); };
  var money = function (v, d) { return "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }); };
  var pct = function (v) { return (v * 100).toFixed(1) + "%"; };
  var css = function (n) { return getComputedStyle(root).getPropertyValue(n).trim(); };
  var fmtDay = function (s) { var d = new Date(s + "T12:00:00"); return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }); };

  $("asof").textContent = D.generated_for;
  D.locations.forEach(function (l, i) {
    var b = document.createElement("button");
    b.textContent = l.name; b.setAttribute("aria-pressed", String(i === 0));
    b.onclick = function () { state.loc = i; draw(); };
    $("locs").appendChild(b);
  });
  document.querySelectorAll("#range button").forEach(function (b) {
    b.onclick = function () { state.days = +b.dataset.d; draw(); };
  });
  $("theme").onclick = function () {
    root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
    try { localStorage.setItem("fc-theme", root.dataset.theme); } catch (e) {}
    draw();
  };
  $("csv").onclick = function () {
    var l = D.locations[state.loc];
    var rows = ["location,date,forecast,low_80,high_80"].concat(l.forecast.map(function (r) { return [l.key, r[0], r[1], r[2], r[3]].join(","); }));
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.join("\n") + "\n"], { type: "text/csv" }));
    a.download = "larkspur-" + l.key + "-forecast-" + D.generated_for + ".csv";
    a.click();
  };

  function chart(l) {
    var W = 1160, H = 360, P = { l: 58, r: 16, t: 14, b: 30 };
    var hist = state.days ? l.history.slice(-state.days) : l.history;
    var all = hist.map(function (r) { return r[0]; }).concat(l.forecast.map(function (r) { return r[0]; }));
    var t0 = new Date(all[0]).getTime(), t1 = new Date(all[all.length - 1]).getTime();
    var maxV = 0;
    hist.forEach(function (r) { if (r[1] != null) maxV = Math.max(maxV, r[1]); });
    l.forecast.forEach(function (r) { maxV = Math.max(maxV, r[3]); });
    maxV = Math.ceil(maxV / 500) * 500;
    var x = function (d) { return P.l + (new Date(d).getTime() - t0) / (t1 - t0) * (W - P.l - P.r); };
    var y = function (v) { return H - P.b - v / maxV * (H - P.t - P.b); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Revenue history and forecast for ' + l.name + '">';
    for (var v = 0; v <= maxV; v += maxV / 5) {
      s += '<line class="gridline" x1="' + P.l + '" x2="' + (W - P.r) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>';
      s += '<text class="axis" x="' + (P.l - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + (v >= 1000 ? "$" + (v / 1000).toFixed(1) + "k" : "$" + v) + "</text>";
    }
    var months = {};
    all.forEach(function (d) { var m = d.slice(0, 7); if (!months[m]) months[m] = d; });
    Object.keys(months).forEach(function (m, i, arr) {
      if (arr.length > 14 && i % 3) return;
      var d = new Date(months[m] + "T12:00:00");
      s += '<text class="axis" x="' + x(months[m]) + '" y="' + (H - 8) + '">' + d.toLocaleDateString("en-US", { month: "short" }) + (d.getMonth() === 0 || i === 0 ? " " + d.getFullYear() : "") + "</text>";
    });
    // forecast band
    var band = l.forecast.map(function (r) { return x(r[0]) + "," + y(r[3]); }).join(" ") + " " +
      l.forecast.slice().reverse().map(function (r) { return x(r[0]) + "," + y(r[2]); }).join(" ");
    s += '<polygon points="' + band + '" fill="' + css("--band") + '"/>';
    // history, broken at gaps
    var path = "", pen = false;
    hist.forEach(function (r) {
      if (r[1] == null) { pen = false; return; }
      path += (pen ? "L" : "M") + x(r[0]).toFixed(1) + " " + y(r[1]).toFixed(1); pen = true;
    });
    s += '<path d="' + path + '" fill="none" stroke="' + css("--grey") + '" stroke-width="1.4"/>';
    // gap marker
    var gap = hist.filter(function (r) { return r[1] == null; });
    if (gap.length) {
      var gx0 = x(gap[0][0]), gx1 = x(gap[gap.length - 1][0]);
      s += '<rect x="' + gx0 + '" y="' + P.t + '" width="' + Math.max(gx1 - gx0, 3) + '" height="' + (H - P.t - P.b) + '" fill="' + css("--raised") + '" opacity=".9"/>';
      s += '<text class="axis" x="' + (gx1 + 6) + '" y="' + (P.t + 14) + '">No data: register outage</text>';
    }
    var f = l.forecast.map(function (r, i) { return (i ? "L" : "M") + x(r[0]).toFixed(1) + " " + y(r[1]).toFixed(1); }).join("");
    s += '<path d="' + f + '" fill="none" stroke="' + css("--accent") + '" stroke-width="2.4" stroke-linejoin="round"/>';
    var lx = x(l.forecast[0][0]);
    s += '<line x1="' + lx + '" x2="' + lx + '" y1="' + P.t + '" y2="' + (H - P.b) + '" stroke="' + css("--faint") + '" stroke-dasharray="3 4"/>';
    var nearEdge = lx > W - P.r - 90;
    s += '<text class="axis" x="' + (nearEdge ? lx - 6 : lx + 6) + '" y="' + (P.t + 14) + '" text-anchor="' + (nearEdge ? "end" : "start") + '">forecast</text>';
    return s + "</svg>";
  }

  function draw() {
    var l = D.locations[state.loc], m = D.metrics, pl = m.per_location[l.key];
    document.querySelectorAll("#locs button").forEach(function (b, i) { b.setAttribute("aria-pressed", String(i === state.loc)); });
    document.querySelectorAll("#range button").forEach(function (b) { b.setAttribute("aria-pressed", String(+b.dataset.d === state.days)); });
    var tot = 0, lo = 0, hi = 0, peak = l.forecast[0];
    l.forecast.forEach(function (r) { tot += r[1]; lo += r[2]; hi += r[3]; if (r[1] > peak[1]) peak = r; });
    $("k-total").textContent = money(tot);
    $("k-range").textContent = "daily ranges sum to " + money(lo) + " to " + money(hi);
    $("k-wape").textContent = pct(pl.wape_model);
    $("k-wape-n").textContent = "vs " + pct(pl.wape_naive);
    $("k-peak").textContent = money(peak[1]);
    $("k-peak-d").textContent = fmtDay(peak[0]) + ", range " + money(peak[2]) + " to " + money(peak[3]);
    $("k-cov").textContent = pct(m.overall.interval_coverage_80);
    $("chart-title").textContent = l.name + ": revenue and forecast";
    $("chart").innerHTML = chart(l);

    var names = {}; D.locations.forEach(function (x) { names[x.key] = x.name; });
    var rows = '<tr><th>Location</th><th class="r">WAPE model</th><th class="r">WAPE naive</th><th class="r">MAPE model</th><th class="r">MAPE naive</th></tr>';
    D.locations.forEach(function (x) {
      var p = m.per_location[x.key];
      rows += "<tr" + (x.key === l.key ? ' style="background:var(--raised)"' : "") + "><td>" + names[x.key] + '</td><td class="r better">' + pct(p.wape_model) + '</td><td class="r">' + pct(p.wape_naive) +
        '</td><td class="r better">' + pct(p.mape_model) + '</td><td class="r">' + pct(p.mape_naive) + "</td></tr>";
    });
    rows += '<tr><td><b>All stores</b></td><td class="r better"><b>' + pct(m.overall.wape_model) + '</b></td><td class="r"><b>' + pct(m.overall.wape_naive) + '</b></td><td class="r better"><b>' + pct(m.overall.mape_model) + '</b></td><td class="r"><b>' + pct(m.overall.mape_naive) + "</b></td></tr>";
    $("bt").innerHTML = rows;
    $("bt-note").textContent = m.folds.length + " folds x " + m.horizon_days + " days, " + m.overall.days_scored + " store-days";

    var imp = m.importance.slice(0, 8), top = imp[0].mae_increase;
    $("imp").innerHTML = imp.map(function (r, i) {
      return '<div class="bar' + (i === 0 ? " top" : "") + '"><span>' + r.feature + '</span><div class="t"><div class="f" style="width:' + Math.max(2, r.mae_increase / top * 100) + '%"></div></div><span class="v">$' + Math.round(r.mae_increase) + "</span></div>";
    }).join("");
  }
  draw();
})();

const F = window.FORECAST;

const money = (v) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const round0 = (v) => Math.round(v).toLocaleString("en-US");
const esc = (s) => String(s).replace(/[&<>]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[m]));
const day = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US",
  { weekday: "long", month: "long", day: "numeric" });

const store = document.getElementById("store");
const bake = document.getElementById("bake");

function fail(message) {
  document.querySelector(".wrap").innerHTML =
    `<h1 style="font-family:Gloock,Georgia,serif;font-weight:400">Larkspur Bakehouse</h1>
     <div class="card" style="margin-top:18px">
       <h2>The forecast did not load</h2>
       <p class="lede">${esc(message)}</p>
       <p class="state">The page needs <strong>data.js</strong>, which the pipeline writes on every run.
          Run <strong>python -m forecast.run</strong> and reload.</p>
     </div>`;
}

if (!F || !F.locations || !F.locations.length) {
  fail("No forecast data was found on this page.");
} else {
  F.locations.forEach((loc, index) => {
    const option = document.createElement("option");
    option.value = index;
    option.textContent = loc.name;
    store.appendChild(option);
  });
  store.addEventListener("change", () => draw(Number(store.value), 0));
  document.getElementById("print").addEventListener("click", () => window.print());
  document.getElementById("csv").addEventListener("click", () => downloadCsv(Number(store.value)));
  draw(0);
}

function draw(index, dayIndex = 0) {
  const loc = F.locations[index];
  const picker = document.getElementById("daypick");
  picker.innerHTML = loc.days.map((d, i) =>
    `<option value="${i}"${i === dayIndex ? " selected" : ""}>${esc(day(d.date))}${d.closed ? ", shut" : ""}</option>`).join("");
  picker.onchange = () => draw(index, Number(picker.value));
  drawBakeList(loc, dayIndex);
  drawChart(loc);
  drawBacktest(loc);
  document.getElementById("stamp").textContent =
    `Forecast made from sales to ${day(F.generated_for)}.`;
}

function drawBakeList(loc, dayIndex = 0) {
  const t = (loc.days && loc.days[dayIndex]) || loc.tomorrow;
  if (!t) {
    bake.innerHTML = `<h2>That day</h2><div class="card state">No forecast day is available for this location.</div>`;
    return;
  }
  if (t.closed) {
    bake.innerHTML = `<h2>Nothing to bake for ${esc(loc.name)} that day</h2>
      <p class="lede">${esc(day(t.date))}</p>
      <div class="card state">This shop is shut on ${esc(t.weekday)}s, so the list is empty rather than zero.
        The forecast still runs for the other days, and the chart below shows them.</div>`;
    return;
  }

  const rows = t.items.map((item) => `
    <div class="row">
      <div><span class="name">${esc(item.name)}</span><span class="unit">${esc(item.unit)}</span></div>
      <div><span class="qty">${item.low} to ${item.high}</span>
        <span class="bake">bake ${item.bake}, trays of ${item.batch}</span></div>
    </div>`).join("");

  const lead = dayIndex === 0 ? "Tomorrow at" : "At";
  bake.innerHTML = `
    <h2>${lead} ${esc(loc.name)}</h2>
    <p class="lede">${esc(day(t.date))}</p>
    <div class="card">
      <div class="list">${rows}</div>
      <div class="total">
        <div class="big">${money(t.revenue)} expected, ${money(t.low)} to ${money(t.high)}</div>
        <p class="why">Counts come from that range and the shop's own menu prices and weekday mix,
           then round up to whole trays, so the oven is planned rather than the till.</p>
      </div>
    </div>`;
}

function drawChart(loc) {
  const W = 1100, H = 330, L = 56, R = 18, T = 16, B = 34;
  const history = loc.history.filter((d) => d[1] !== null).slice(-120);
  const forecast = loc.forecast;
  const all = history.map((d) => d[1]).concat(forecast.map((d) => d[3]));
  const top = Math.max(...all) * 1.08;
  const dates = history.map((d) => d[0]).concat(forecast.map((d) => d[0]));
  const x = (i) => L + (i / (dates.length - 1)) * (W - L - R);
  const y = (v) => H - B - (v / top) * (H - T - B);

  const histPath = history.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[1]).toFixed(1)}`).join("");
  const offset = history.length;
  const fcPath = forecast.map((d, i) => `${i ? "L" : "M"}${x(offset + i).toFixed(1)},${y(d[1]).toFixed(1)}`).join("");
  const bandTop = forecast.map((d, i) => `${i ? "L" : "M"}${x(offset + i).toFixed(1)},${y(d[3]).toFixed(1)}`).join("");
  const bandBottom = forecast.slice().reverse()
    .map((d, i) => `L${x(offset + forecast.length - 1 - i).toFixed(1)},${y(d[2]).toFixed(1)}`).join("");

  const ticks = [0, 0.5, 1].map((p) => {
    const v = top * p;
    return `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"></line>
            <text class="axis" x="6" y="${y(v) + 4}">${"$" + round0(v)}</text>`;
  }).join("");

  // Annotations sit above the forecast line on a hairline leader. Only real
  // events from the data appear: planned promotions and US holidays.
  const seen = new Set();
  const notes = (loc.notes || []).filter((n) => {
    if (seen.has(n.text)) return false;
    seen.add(n.text);
    return true;
  }).slice(0, 3).map((n, rank) => {
    const i = forecast.findIndex((d) => d[0] === n.date);
    if (i < 0) return "";
    // Notes live in their own lane at the top of the plot and drop a hairline
    // to the day they belong to, so they never cross the forecast line.
    const px = x(offset + i), py = y(forecast[i][3]);
    const lane = T + 16 + rank * 17;
    const anchor = px > W - 220 ? "end" : "start";
    return `<line class="note-leader" x1="${px}" y1="${lane + 4}" x2="${px}" y2="${py - 5}"></line>
            <text class="note-text" x="${px + (anchor === "end" ? -6 : 6)}" y="${lane}"
                  text-anchor="${anchor}">${esc(n.text)}</text>`;
  }).join("");

  const firstForecast = x(offset);
  document.getElementById("chart").innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily sales and the 28 day forecast">
      ${ticks}
      <path class="bandfill" d="${bandTop}${bandBottom}Z"></path>
      <path class="hist" d="${histPath}"></path>
      <path class="fc" d="${fcPath}"></path>
      <line class="gridline" x1="${firstForecast}" x2="${firstForecast}" y1="${T}" y2="${H - B}"></line>
      <text class="axis" x="${firstForecast + 5}" y="${T + 11}">forecast starts</text>
      ${notes}
      <text class="axis" x="${L}" y="${H - 10}">${dates[0]}</text>
      <text class="axis" x="${W - R}" y="${H - 10}" text-anchor="end">${dates[dates.length - 1]}</text>
    </svg>`;

  const total = forecast.reduce((sum, d) => sum + d[1], 0);
  document.getElementById("chart-lede").textContent =
    `${loc.name} is forecast to take ${money(total)} over the next ${F.horizon} days. `
    + `The band is the range the model expects to be right about 80% of the time.`;
}

function drawBacktest(loc) {
  const m = F.metrics;
  const rows = Object.entries(m.per_location).map(([key, v]) => {
    const name = (F.locations.find((l) => l.key === key) || {}).name || key;
    return `<tr><td>${esc(name)}</td><td class="r">${(v.wape_model * 100).toFixed(1)}%</td>
            <td class="r">${(v.wape_naive * 100).toFixed(1)}%</td></tr>`;
  }).join("");
  document.getElementById("bt-rows").innerHTML = rows;

  const o = m.overall;
  document.getElementById("bt-lede").textContent =
    `Six rounds, each forecasting ${F.horizon} days the model had never seen, ${o.days_scored} store days in all.`;
  document.getElementById("bt-notes").innerHTML =
    `<p>Across every round the forecast was out by <strong>${(o.wape_model * 100).toFixed(1)}%</strong>,
        against <strong>${(o.wape_naive * 100).toFixed(1)}%</strong> for simply repeating last week.</p>
     <p>The 80% range held on <strong>${(o.interval_coverage_80 * 100).toFixed(1)}%</strong> of days,
        which is what an honest 80% range should do, and the forecast ran
        <strong>${(o.bias_model * 100).toFixed(1)}%</strong> against actual sales overall.</p>`;
}

function downloadCsv(index) {
  const loc = F.locations[index];
  const header = "date,location,forecast,low_80,high_80\n";
  const body = loc.forecast.map((d) => [d[0], loc.key, d[1].toFixed(2), d[2].toFixed(2), d[3].toFixed(2)].join(",")).join("\n");
  const blob = new Blob([header + body + "\n"], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `larkspur-${loc.key}-forecast.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

"use strict";

const CSV_URL = "./data/btc_production_cost.csv";
const SPOT_URL = "https://api.coinbase.com/v2/prices/BTC-USD/spot";

const HALVINGS = [
  { date: "2012-11-28", label: "Halving 2012" },
  { date: "2016-07-09", label: "Halving 2016" },
  { date: "2020-05-11", label: "Halving 2020" },
  { date: "2024-04-20", label: "Halving 2024" },
];

const FNG_BUY_THRESHOLD = 9;

const fmtUSD = (n, max = 0) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", maximumFractionDigits: max }).format(n);

function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  const header = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const cells = line.split(",");
    const row = {};
    header.forEach((h, i) => (row[h] = cells[i]));
    return row;
  });
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

async function loadSeries() {
  const res = await fetch(CSV_URL, { cache: "no-store" });
  if (!res.ok) throw new Error("CSV não encontrado: " + res.status);
  const rows = parseCSV(await res.text()).filter((r) => r.date && r.production_cost_usd);
  return rows;
}

async function fetchSpot() {
  try {
    const res = await fetch(SPOT_URL, { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    const amount = parseFloat(data?.data?.amount);
    return Number.isFinite(amount) ? amount : null;
  } catch {
    return null;
  }
}

async function fetchFearGreed() {
  try {
    const res = await fetch("https://api.alternative.me/fng/?limit=1", { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    const entry = data?.data?.[0];
    return entry ? { value: parseInt(entry.value, 10), classification: entry.value_classification } : null;
  } catch {
    return null;
  }
}

function renderFloor(latestCost, spot) {
  setText("cost", fmtUSD(latestCost));
  if (spot == null) {
    setText("spot", "indisponível");
    document.getElementById("spot-note").textContent = "spot Coinbase fora do ar";
    document.getElementById("gauge").style.opacity = "0.55";
    return;
  }
  setText("spot", fmtUSD(spot));
  const mult = spot / latestCost;
  setText("multiple", mult.toFixed(2) + "×");

  // gauge: custo fica fixo em 33%; a barra do preço escala proporcional ao múltiplo
  const floorPct = 33;
  const fillPct = Math.max(4, Math.min(100, floorPct * mult));
  document.getElementById("gauge-fill").style.width = fillPct + "%";

  const pill = document.getElementById("status-pill");
  if (spot >= latestCost) {
    pill.textContent = "acima do custo";
    pill.classList.add("pill--above");
  } else {
    pill.textContent = "abaixo do custo";
    pill.classList.add("pill--below");
  }
}

function renderCards(rows) {
  const last = rows[rows.length - 1];
  setText("card-cost", fmtUSD(parseFloat(last.production_cost_usd)));
  setText("card-cost-date", last.date);
  setText("card-twh", parseFloat(last.annualized_twh).toFixed(0) + " TWh");
  setText("card-price", fmtUSD(parseFloat(last.energy_price_usd_kwh), 3));
  setText("card-issued", parseFloat(last.btc_issued_per_day).toFixed(0));
  setText("updated", "atualizado " + last.date + (last.source === "demo" ? " · DEMO" : ""));
}

function renderFearGreed(fng) {
  if (!fng) {
    setText("fng-value", "—");
    setText("fng-class", "indisponível");
    return;
  }
  const { value, classification } = fng;
  setText("fng-value", value);
  setText("fng-class", classification);
  document.getElementById("fng-needle").style.left = value + "%";
  const signal = document.getElementById("fng-signal");
  if (value <= FNG_BUY_THRESHOLD) {
    signal.textContent = "ZONA DE COMPRA";
    signal.classList.add("fng-signal--active");
  }
}

function movingAvg(arr, window) {
  return arr.map((_, i) => {
    const start = Math.max(0, i - window + 1);
    const slice = arr.slice(start, i + 1).filter((v) => v != null && isFinite(v));
    return slice.length ? slice.reduce((s, v) => s + v, 0) / slice.length : null;
  });
}

function renderChart(rows, candles) {
  // Filtrar ultimos 5 anos
  const cutoff = new Date();
  cutoff.setFullYear(cutoff.getFullYear() - 5);
  const cutStr = cutoff.toISOString().slice(0, 10);
  const rows5 = rows.filter((r) => r.date >= cutStr);

  const labels = rows5.map((r) => r.date);
  const rawCost  = rows5.map((r) => parseFloat(r.production_cost_usd));

  // Preco BTC: fecha diario das velas
  const priceMap = new Map((candles || []).map((c) => [c.time, c.close]));
  const btcPrice = labels.map((d) => priceMap.get(d) ?? null);

  const buyZonePlugin = {
    id: "buyZone",
    beforeDatasetsDraw(chart) {
      const { ctx, scales: { x: xScale, y: yScale }, data: { datasets } } = chart;
      const prices = datasets[0].data;
      const costs = datasets[1].data;
      const meta = chart.getDatasetMeta(0);
      if (!meta.data.length) return;
      ctx.save();
      ctx.fillStyle = "rgba(91,211,126,0.15)";
      let i = 0;
      while (i < prices.length) {
        const p = prices[i], c = costs[i];
        if (p != null && c != null && p < c) {
          let j = i;
          while (j < prices.length && prices[j] != null && costs[j] != null && prices[j] < costs[j]) j++;
          ctx.beginPath();
          for (let m = i; m < j; m++) {
            const x = meta.data[m].x, y = yScale.getPixelForValue(costs[m]);
            m === i ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
          }
          for (let m = j - 1; m >= i; m--) {
            ctx.lineTo(meta.data[m].x, yScale.getPixelForValue(prices[m]));
          }
          ctx.closePath();
          ctx.fill();
          i = j;
        } else {
          i++;
        }
      }
      ctx.restore();
    },
  };

  const halvingPlugin = {
    id: "halvings",
    afterDraw(chart) {
      const { ctx, scales: { x: xScale, y: yScale }, data: { labels } } = chart;
      HALVINGS.forEach(({ date, label }) => {
        const idx = labels.indexOf(date);
        if (idx === -1) return;
        const px = xScale.getPixelForValue(idx);
        ctx.save();
        ctx.beginPath();
        ctx.strokeStyle = "#FF5C5C";
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.moveTo(px, yScale.top);
        ctx.lineTo(px, yScale.bottom);
        ctx.stroke();
        ctx.fillStyle = "#FF5C5C";
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.fillText(label, px + 4, yScale.top + 14);
        ctx.restore();
      });
    },
  };

  // eslint-disable-next-line no-undef
  new Chart(document.getElementById("costChart"), {
    plugins: [buyZonePlugin, halvingPlugin],
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Preco BTC (USD)",
          data: btcPrice,
          borderColor: "#4DD0C4",
          backgroundColor: "transparent",
          borderWidth: 1.5,
          fill: false,
          pointRadius: 0,
          tension: 0.12,
          order: 1,
        },
        {
          label: "Custo real CBECI (diario)",
          data: rawCost,
          borderColor: "#FFB000",
          backgroundColor: "rgba(255,176,0,0.07)",
          borderWidth: 1.5,
          fill: true,
          pointRadius: 0,
          tension: 0,
          order: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: { color: "#8B95A1", usePointStyle: true, pointStyleWidth: 12, padding: 20 },
        },
        tooltip: {
          callbacks: { label: (c) => `${c.dataset.label}: ${fmtUSD(c.parsed.y)}` },
        },
      },
      scales: {
        x: { ticks: { color: "#8B95A1", maxTicksLimit: 8 }, grid: { color: "#232A33" } },
        y: {
          ticks: { color: "#8B95A1", callback: (v) => fmtUSD(v) },
          grid: { color: "#232A33" },
        },
      },
    },
  });
}

async function fetchBTCCandles() {
  const toCandle = ([ts, o, h, l, c]) => ({
    time: new Date(ts).toISOString().slice(0, 10),
    open: parseFloat(o), high: parseFloat(h),
    low: parseFloat(l), close: parseFloat(c),
  });
  const base = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=1000";
  const fiveYearsMs = Date.now() - 5 * 365 * 24 * 60 * 60 * 1000;
  try {
    const r1 = await fetch(`${base}&startTime=${fiveYearsMs}`, { cache: "no-store" });
    const raw1 = r1.ok ? (await r1.json()).map(toCandle) : [];
    let raw2 = [];
    if (raw1.length === 1000) {
      const nextTs = new Date(raw1[raw1.length - 1].time + "T00:00:00Z").getTime() + 86400000;
      const r2 = await fetch(`${base}&startTime=${nextTs}`, { cache: "no-store" });
      raw2 = r2.ok ? (await r2.json()).map(toCandle) : [];
    }
    const seen = new Set();
    return [...raw1, ...raw2].filter((c) => {
      if (seen.has(c.time)) return false;
      seen.add(c.time); return true;
    });
  } catch {
    return [];
  }
}

function renderLightweightChart(rows, candles) {
  const container = document.getElementById("tv-chart");
  // eslint-disable-next-line no-undef
  if (typeof LightweightCharts === "undefined" || !container) return;

  // eslint-disable-next-line no-undef
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight || 480,
    layout: { background: { color: "#141B22" }, textColor: "#8B95A1" },
    grid: { vertLines: { color: "#232A33" }, horzLines: { color: "#232A33" } },
    // eslint-disable-next-line no-undef
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: "#232A33" },
    timeScale: { borderColor: "#232A33", timeVisible: false },
  });

  new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth });
  }).observe(container);

  if (candles.length) {
    const cs = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });
    cs.setData(candles);
    const candleTimes = new Set(candles.map((c) => c.time));
    const markers = HALVINGS
      .filter((h) => candleTimes.has(h.date))
      .map((h) => ({
        time: h.date,
        position: "belowBar",
        color: "#FF5C5C",
        shape: "arrowUp",
        text: h.label,
        size: 1,
      }));
    if (markers.length) cs.setMarkers(markers);
  }

  const costRows = rows.filter((r) => r.date && r.production_cost_usd);

  // Buy zone strip: verde fino no rodapé quando preço < custo de produção
  if (candles.length && costRows.length) {
    const costByDate = new Map(costRows.map((r) => [r.date, parseFloat(r.production_cost_usd)]));
    const bzData = candles
      .filter((c) => { const cost = costByDate.get(c.time); return cost != null && c.close < cost; })
      .map((c) => ({ time: c.time, value: 1, color: "rgba(91,211,126,0.45)" }));
    if (bzData.length) {
      const bzSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "bz",
        lastValueVisible: false,
        priceLineVisible: false,
      });
      chart.priceScale("bz").applyOptions({ scaleMargins: { top: 0.93, bottom: 0 }, visible: false });
      bzSeries.setData(bzData);
    }
  }
  if (costRows.length) {
    const rawVals = costRows.map((r) => parseFloat(r.production_cost_usd));
    const smoothVals = movingAvg(rawVals, 30);
    const ls = chart.addLineSeries({
      color: "#FFB000",
      lineWidth: 2,
      title: "Custo MA30",
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    });
    ls.setData(
      costRows
        .map((r, i) => ({ time: r.date, value: smoothVals[i] }))
        .filter((p) => p.value != null)
    );
  }

  chart.timeScale().fitContent();
}

(async function init() {
  try {
    const [rows, spot, candles, fng] = await Promise.all([loadSeries(), fetchSpot(), fetchBTCCandles(), fetchFearGreed()]);
    if (!rows.length) throw new Error("série vazia");
    renderCards(rows);
    renderChart(rows, candles);
    renderLightweightChart(rows, candles);
    renderFloor(parseFloat(rows[rows.length - 1].production_cost_usd), spot);
    renderFearGreed(fng);
  } catch (err) {
    setText("updated", "erro ao carregar dados");
    setText("cost", "—");
    console.error(err);
  }
})();

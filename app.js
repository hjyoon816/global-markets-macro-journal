const DATA_URL = "data/market-data.json";
const ARCHIVE_URL = "data/archive.json";
const HISTORY_URL = "data/history.json";
const PLACEHOLDER = "—";
const ONE_DAY_MS = 24 * 60 * 60 * 1000;

const appState = {
  chartRange: "3M",
  charts: [],
  instruments: new Map(),
};

const byId = (id) => document.getElementById(id);

const isPlaceholder = (value) =>
  value === undefined ||
  value === null ||
  value === "" ||
  value === PLACEHOLDER ||
  (Array.isArray(value) && value.length === 0);

const text = (value) => (isPlaceholder(value) ? PLACEHOLDER : String(value));

const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const slug = (value) =>
  String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");

const safeHref = (url) => {
  if (isPlaceholder(url)) {
    return "";
  }

  try {
    const parsed = new URL(String(url), window.location.href);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "";
  } catch (error) {
    return "";
  }
};

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Unable to load ${url}`);
  }
  return response.json();
}

function classifyDataStatus(metadata) {
  const lastSuccessfulUpdate = metadata?.lastSuccessfulUpdate;

  if (isPlaceholder(lastSuccessfulUpdate)) {
    return {
      key: "setup",
      label: "Setup / data pipeline pending",
      detail: "No successful market-data update has been recorded.",
    };
  }

  const parsed = Date.parse(lastSuccessfulUpdate);
  if (Number.isNaN(parsed)) {
    return {
      key: "error",
      label: "Timestamp unavailable",
      detail: "lastSuccessfulUpdate is not a valid ISO timestamp.",
    };
  }

  const ageMs = Date.now() - parsed;
  if (ageMs > ONE_DAY_MS) {
    return {
      key: "stale",
      label: "Stale data",
      detail: "The latest successful update is more than 24 hours old.",
    };
  }

  return {
    key: "current",
    label: "Data current",
    detail: "The latest successful update is within 24 hours.",
  };
}

function renderDataStatus(metadata) {
  const status = classifyDataStatus(metadata);

  byId("data-status-banner").innerHTML = `
    <article class="status-card ${escapeHtml(status.key)}">
      <span class="status-label">${escapeHtml(status.label)}</span>
      <div class="status-meta">
        <span>As of: ${escapeHtml(text(metadata?.asOf))}</span>
        <span>Last successful update: ${escapeHtml(text(metadata?.lastSuccessfulUpdate))}</span>
        <span>Status: ${escapeHtml(text(metadata?.status))}</span>
        <span>${escapeHtml(status.detail)}</span>
      </div>
    </article>
  `;
}

function renderToday(today) {
  const regime = today?.macroRegime ?? {};
  const rows = [
    ["Inflation risk", regime.inflationRisk],
    ["Growth momentum", regime.growthMomentum],
    ["Policy bias", regime.policyBias],
    ["Liquidity", regime.liquidity],
    ["Risk appetite", regime.riskAppetite],
  ];

  byId("macro-regime-list").innerHTML = rows
    .map(
      ([label, value]) => `
        <div>
          <dt>${escapeHtml(label)}</dt>
          <dd class="${isPlaceholder(value) ? "placeholder" : ""}">${escapeHtml(text(value))}</dd>
        </div>
      `,
    )
    .join("");

  byId("regime-summary").textContent = text(regime.regimeSummary);

  byId("today-focus-list").innerHTML = (today?.researchChecklist ?? [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");

  renderSignals(today?.dashboardSignals ?? [], byId("dashboard-signals"));
}

function renderSignals(signals, target) {
  const safeSignals = signals.slice(0, 5);

  target.innerHTML = safeSignals
    .map(
      (signal) => `
        <article class="signal-card">
          <div class="signal-title">
            <span>${escapeHtml(text(signal.title))}</span>
            <span class="status-chip ${slug(signal.confidence || "pending")}">
              ${escapeHtml(text(signal.confidence))}
            </span>
          </div>
          <div class="signal-body">
            <div>
              <span class="label">Observation</span>
              ${escapeHtml(text(signal.observation))}
            </div>
            <div>
              <span class="label">Interpretation</span>
              ${escapeHtml(text(signal.interpretation))}
            </div>
          </div>
          <div class="asset-tags">
            ${(signal.relatedAssets ?? []).map((asset) => `<span class="tag">${escapeHtml(asset)}</span>`).join("")}
          </div>
        </article>
      `,
    )
    .join("");
}

function changeClass(value) {
  if (isPlaceholder(value)) {
    return "direction-flat";
  }

  const numeric = Number.parseFloat(String(value).replace(/,/g, ""));
  if (!Number.isFinite(numeric) || numeric === 0) {
    return "direction-flat";
  }

  return numeric > 0 ? "direction-up" : "direction-down";
}

function formatChange(value, unit) {
  if (isPlaceholder(value)) {
    return PLACEHOLDER;
  }

  return isPlaceholder(unit) ? String(value) : `${value} ${unit}`;
}

function sourceHtml(item) {
  const href = safeHref(item.sourceUrl);
  if (href) {
    return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(text(item.sourceName))}</a>`;
  }
  return `<span>${escapeHtml(text(item.sourceName))}</span>`;
}

function statusChip(item) {
  const status = item.verified ? "verified" : text(item.status).toLowerCase();
  const label = item.verified ? "Verified" : text(item.status);
  return `<span class="status-chip ${escapeHtml(slug(status))}">${escapeHtml(label)}</span>`;
}

function instrumentCard(instrument, options = {}) {
  if (!instrument) {
    return "";
  }

  const prominent = options.prominent ? " prominent" : "";

  return `
    <article class="instrument-card${prominent}">
      <div class="instrument-topline">
        <span>
          <span class="instrument-name">${escapeHtml(instrument.name)}</span>
          <span class="instrument-meta">${escapeHtml(text(instrument.region))} / ${escapeHtml(text(instrument.assetClass))} / ${escapeHtml(text(instrument.unit))}</span>
        </span>
        ${statusChip(instrument)}
      </div>
      <div class="instrument-latest ${isPlaceholder(instrument.latest) ? "placeholder" : ""}">
        ${escapeHtml(text(instrument.latest))}
      </div>
      <div class="instrument-changes">
        <div class="change-box">
          <span class="label">1D</span>
          <span class="change-value ${changeClass(instrument.change1d)}">${escapeHtml(formatChange(instrument.change1d, instrument.changeUnit))}</span>
        </div>
        <div class="change-box">
          <span class="label">1W</span>
          <span class="change-value ${changeClass(instrument.change1w)}">${escapeHtml(formatChange(instrument.change1w, instrument.changeUnit))}</span>
        </div>
      </div>
      <div class="instrument-foot">
        <span>Timestamp: ${escapeHtml(text(instrument.timestamp))}</span>
        <span>Source: ${sourceHtml(instrument)}</span>
        <span>Interpretation: ${escapeHtml(text(instrument.interpretation))}</span>
      </div>
    </article>
  `;
}

function renderMarketDashboard(groups) {
  byId("market-dashboard").innerHTML = groups
    .map((group) => {
      const instruments = group.instrumentIds
        .map((id) => appState.instruments.get(id))
        .filter(Boolean);

      return `
        <section class="dashboard-group" id="${escapeHtml(group.id)}">
          <div class="group-header">
            <p class="eyebrow">${escapeHtml(group.kicker)}</p>
            <h3>${escapeHtml(group.title)}</h3>
            <p>${escapeHtml(group.description)}</p>
          </div>
          <div class="instrument-grid">
            ${instruments.map((instrument) => instrumentCard(instrument)).join("")}
          </div>
        </section>
      `;
    })
    .join("");
}

function renderAssetBoards(groups) {
  byId("asset-class-board").innerHTML = groups
    .map((group) => {
      const instruments = group.instrumentIds
        .map((id) => appState.instruments.get(id))
        .filter(Boolean);

      return `
        <section class="asset-panel" id="${escapeHtml(group.id)}">
          <div class="asset-header">
            <p class="eyebrow">${escapeHtml(group.kicker)}</p>
            <h3>${escapeHtml(group.title)}</h3>
            <p>${escapeHtml(group.description)}</p>
          </div>
          <div class="asset-table">
            <div class="asset-row header">
              <span>Instrument</span>
              <span>Latest</span>
              <span>1D</span>
              <span>1W</span>
            </div>
            ${instruments
              .map(
                (instrument) => `
                  <div class="asset-row">
                    <strong>${escapeHtml(instrument.name)}</strong>
                    <span class="${isPlaceholder(instrument.latest) ? "placeholder" : ""}">${escapeHtml(text(instrument.latest))}</span>
                    <span class="${changeClass(instrument.change1d)}">${escapeHtml(formatChange(instrument.change1d, instrument.changeUnit))}</span>
                    <span class="${changeClass(instrument.change1w)}">${escapeHtml(formatChange(instrument.change1w, instrument.changeUnit))}</span>
                  </div>
                `,
              )
              .join("")}
          </div>
        </section>
      `;
    })
    .join("");
}

function placeholderStory(rank) {
  return {
    rank,
    headline: PLACEHOLDER,
    category: PLACEHOLDER,
    summary: PLACEHOLDER,
    whyTop5: PLACEHOLDER,
    causalChain: [PLACEHOLDER],
    assetImpact: {
      rates: PLACEHOLDER,
      fx: PLACEHOLDER,
      equities: PLACEHOLDER,
      credit: PLACEHOLDER,
      commodities: PLACEHOLDER,
      digitalAssets: PLACEHOLDER,
    },
    learningTakeaway: PLACEHOLDER,
    imageUrl: PLACEHOLDER,
    sources: [{ name: PLACEHOLDER, url: PLACEHOLDER, type: "primary" }],
  };
}

function normalizeTopStories(stories) {
  const byRank = new Map((stories ?? []).map((story) => [Number(story.rank), story]));
  return Array.from({ length: 5 }, (_, index) => byRank.get(index + 1) ?? placeholderStory(index + 1));
}

function storyCard(story) {
  const impact = story.assetImpact ?? {};
  const sourceList = (story.sources ?? [])
    .map((source) => {
      const href = safeHref(source.url);
      const label = `${text(source.name)} (${text(source.type)})`;
      return href
        ? `<li><a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(label)}</a></li>`
        : `<li>${escapeHtml(label)}</li>`;
    })
    .join("");

  return `
    <article class="story-card">
      <span class="story-rank">${escapeHtml(text(story.rank))}</span>
      <div class="story-body">
        <div>
          <p class="eyebrow">${escapeHtml(text(story.category))}</p>
          <h3>${escapeHtml(text(story.headline))}</h3>
        </div>
        <div class="story-summary-grid">
          <div class="field-box"><strong>Summary</strong>${escapeHtml(text(story.summary))}</div>
          <div class="field-box"><strong>Why Top 5</strong>${escapeHtml(text(story.whyTop5))}</div>
          <div class="field-box"><strong>Learning Takeaway</strong>${escapeHtml(text(story.learningTakeaway))}</div>
        </div>
        <div class="field-box">
          <strong>Causal Chain</strong>
          <ul>${(story.causalChain ?? [PLACEHOLDER]).map((point) => `<li>${escapeHtml(text(point))}</li>`).join("")}</ul>
        </div>
        <div class="impact-grid">
          ${["rates", "fx", "equities", "credit", "commodities", "digitalAssets"]
            .map((key) => `<div class="field-box"><strong>${escapeHtml(key)}</strong>${escapeHtml(text(impact[key]))}</div>`)
            .join("")}
        </div>
        <div class="field-box">
          <strong>Sources</strong>
          <ul class="source-list">${sourceList}</ul>
        </div>
      </div>
    </article>
  `;
}

function renderTopStories(stories) {
  byId("top-stories-list").innerHTML = normalizeTopStories(stories).map(storyCard).join("");
}

function rangeCutoff(range, latestTime) {
  const days = {
    "1M": 31,
    "3M": 93,
    "6M": 183,
    "1Y": 366,
  }[range];

  return days ? latestTime - days * ONE_DAY_MS : -Infinity;
}

function finitePoint(point) {
  return point && Number.isFinite(point.value) && !Number.isNaN(Date.parse(`${point.date}T00:00:00Z`));
}

function filterSeriesPoints(points, range) {
  const validDates = points
    .filter(finitePoint)
    .map((point) => Date.parse(`${point.date}T00:00:00Z`));

  if (!validDates.length) {
    return points;
  }

  const cutoff = rangeCutoff(range, Math.max(...validDates));
  return points.filter((point) => Date.parse(`${point.date}T00:00:00Z`) >= cutoff);
}

function transformedPoints(series, range, transform) {
  const filtered = filterSeriesPoints(series.points ?? [], range);
  if (transform !== "normalized100") {
    return filtered;
  }

  const base = filtered.find((point) => finitePoint(point) && point.value !== 0)?.value;
  if (!Number.isFinite(base)) {
    return filtered.map((point) => ({ ...point, value: null }));
  }

  return filtered.map((point) => ({
    ...point,
    value: Number.isFinite(point.value) ? (point.value / base) * 100 : null,
  }));
}

function destroyCharts() {
  appState.charts.forEach((chart) => chart.destroy());
  appState.charts = [];
}

function renderChartRangeSelector(history) {
  const ranges = history.ranges ?? ["1M", "3M", "6M", "1Y"];
  const target = byId("chart-range-selector");

  target.innerHTML = ranges
    .map(
      (range) => `
        <button type="button" class="${range === appState.chartRange ? "active" : ""}" data-range="${escapeHtml(range)}">
          ${escapeHtml(range)}
        </button>
      `,
    )
    .join("");

  target.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      appState.chartRange = button.dataset.range;
      renderCharts(history);
    });
  });
}

function renderCharts(history) {
  destroyCharts();
  renderChartRangeSelector(history);

  const seriesById = new Map((history.series ?? []).map((series) => [series.id, series]));
  const grid = byId("charts-grid");

  grid.innerHTML = (history.chartPanels ?? [])
    .map(
      (panel) => `
        <article class="chart-panel">
          <div class="chart-header">
            <p class="eyebrow">${escapeHtml(text(panel.kicker))}</p>
            <h3>${escapeHtml(panel.title)}</h3>
            <p>${escapeHtml(text(panel.description))}</p>
          </div>
          <div class="chart-stage" id="chart-stage-${escapeHtml(panel.id)}"></div>
        </article>
      `,
    )
    .join("");

  (history.chartPanels ?? []).forEach((panel) => {
    const stage = byId(`chart-stage-${panel.id}`);
    const panelSeries = panel.seriesIds.map((id) => seriesById.get(id)).filter(Boolean);
    const prepared = panelSeries.map((series) => ({
      ...series,
      points: transformedPoints(series, appState.chartRange, panel.transform),
    }));
    const labels = Array.from(
      new Set(prepared.flatMap((series) => series.points.map((point) => point.date))),
    ).sort();
    const hasData = prepared.some((series) => series.points.some(finitePoint));

    if (!hasData) {
      stage.innerHTML = `<div class="empty-state">Historical data not yet available</div>`;
      return;
    }

    if (!window.Chart) {
      stage.innerHTML = `<div class="empty-state">Chart library unavailable</div>`;
      return;
    }

    const canvas = document.createElement("canvas");
    stage.append(canvas);

    const colors = ["#265f9f", "#17736f", "#9c6a20", "#6b5678"];
    const datasets = prepared.map((series, index) => {
      const pointsByDate = new Map(series.points.map((point) => [point.date, point.value]));
      return {
        label: series.name,
        data: labels.map((label) => pointsByDate.get(label) ?? null),
        borderColor: colors[index % colors.length],
        backgroundColor: colors[index % colors.length],
        borderWidth: 2,
        pointRadius: 0,
        spanGaps: true,
        tension: 0.25,
      };
    });

    const chart = new Chart(canvas, {
      type: "line",
      data: { labels, datasets },
      options: {
        animation: false,
        maintainAspectRatio: false,
        responsive: true,
        plugins: {
          legend: {
            labels: {
              boxWidth: 10,
              color: "#5b6775",
              font: { size: 11, weight: "700" },
            },
          },
          tooltip: { intersect: false, mode: "index" },
        },
        scales: {
          x: {
            ticks: { color: "#7b8794", maxTicksLimit: 6 },
            grid: { color: "#e9eef2" },
          },
          y: {
            ticks: { color: "#7b8794" },
            grid: { color: "#e9eef2" },
          },
        },
      },
    });

    appState.charts.push(chart);
  });
}

function renderCalendar(events) {
  byId("calendar-body").innerHTML = events
    .map((event) => {
      const status = slug(event.status || "upcoming");
      const importance = slug(event.importance || "");
      return `
        <tr class="${status} ${importance === "high" ? "high-importance" : ""}">
          <td>${escapeHtml(text(event.date))}</td>
          <td>${escapeHtml(text(event.time))}<br /><span class="placeholder">${escapeHtml(text(event.timezone))}</span></td>
          <td>${escapeHtml(text(event.region))}</td>
          <td><strong>${escapeHtml(text(event.event))}</strong></td>
          <td><span class="status-chip ${escapeHtml(status)}">${escapeHtml(text(event.status))}</span><br />${escapeHtml(text(event.importance))}</td>
          <td>${escapeHtml(text(event.actual))}</td>
          <td>${escapeHtml(text(event.consensus))}</td>
          <td>${escapeHtml(text(event.previous))}</td>
          <td>${escapeHtml(text(event.surprise))}</td>
          <td>${escapeHtml(text(event.whyItMatters))}</td>
          <td>${(event.sensitiveMarkets ?? []).map((market) => `<span class="tag">${escapeHtml(market)}</span>`).join(" ") || PLACEHOLDER}</td>
          <td>${sourceHtml(event)}</td>
        </tr>
      `;
    })
    .join("");
}

function flowCard(item) {
  return `
    <article class="flow-card">
      <div class="instrument-topline">
        <span>
          <span class="instrument-name">${escapeHtml(text(item.category))}</span>
          <span class="instrument-meta">${escapeHtml(text(item.frequency))} / ${escapeHtml(text(item.region))}</span>
        </span>
        ${statusChip(item)}
      </div>
      <div class="instrument-latest ${isPlaceholder(item.latest) ? "placeholder" : ""}">
        ${escapeHtml(text(item.latest))}
      </div>
      <p><strong>Interpretation:</strong> ${escapeHtml(text(item.interpretation))}</p>
      <div class="instrument-foot">
        <span>Timestamp: ${escapeHtml(text(item.timestamp))}</span>
        <span>Source: ${sourceHtml(item)}</span>
      </div>
    </article>
  `;
}

function renderPositioning(positioningFlows) {
  const groups = [
    {
      title: "Hard Data",
      kicker: "Observed records",
      items: positioningFlows?.hardData ?? [],
      labelClass: "primary",
    },
    {
      title: "Market Inference",
      kicker: "Pricing-derived signals",
      items: positioningFlows?.marketInference ?? [],
      labelClass: "inference",
    },
  ];

  byId("positioning-grid").innerHTML = groups
    .map(
      (group) => `
        <section class="flow-panel">
          <div class="flow-header">
            <p class="eyebrow">${escapeHtml(group.kicker)}</p>
            <h3>${escapeHtml(group.title)}</h3>
            <span class="tag ${escapeHtml(group.labelClass)}">${escapeHtml(group.title)}</span>
          </div>
          <div class="flow-list">
            ${group.items.map(flowCard).join("")}
          </div>
        </section>
      `,
    )
    .join("");
}

function hasMarketValue(instrument) {
  return (
    instrument &&
    (!isPlaceholder(instrument.latest) ||
      !isPlaceholder(instrument.change1d) ||
      !isPlaceholder(instrument.change1w))
  );
}

function renderDigitalAssets(digitalAssets) {
  const signal = digitalAssets?.cryptoSignal ?? {};
  const macroDrivers = signal.macroDrivers?.length ? signal.macroDrivers : [PLACEHOLDER];
  const cryptoDrivers = signal.cryptoSpecificDrivers?.length ? signal.cryptoSpecificDrivers : [PLACEHOLDER];

  byId("crypto-signal-card").innerHTML = `
    <p class="eyebrow">Crypto signal today</p>
    <h3>${escapeHtml(text(signal.classification))}</h3>
    <p>${escapeHtml(text(signal.summary))}</p>
    <div class="briefing-mini-grid">
      <div>
        <span class="label">Macro drivers</span>
        <ul class="driver-list">${macroDrivers.map((driver) => `<li>${escapeHtml(text(driver))}</li>`).join("")}</ul>
      </div>
      <div>
        <span class="label">Crypto-specific drivers</span>
        <ul class="driver-list">${cryptoDrivers.map((driver) => `<li>${escapeHtml(text(driver))}</li>`).join("")}</ul>
      </div>
    </div>
  `;

  byId("digital-core").innerHTML = (digitalAssets?.coreIds ?? [])
    .map((id) => instrumentCard(appState.instruments.get(id), { prominent: true }))
    .join("");

  const optional = (digitalAssets?.optionalIds ?? [])
    .map((id) => appState.instruments.get(id))
    .filter(hasMarketValue);

  byId("digital-optional").innerHTML = optional.length
    ? optional.map((instrument) => instrumentCard(instrument)).join("")
    : `<div class="empty-state">Optional crypto indicators will appear after verified values are populated.</div>`;
}

function renderGlossary(terms) {
  const grid = byId("glossary-grid");
  const input = byId("glossary-search");

  const paint = () => {
    const query = input.value.trim().toLowerCase();
    const filtered = terms.filter((term) => {
      const haystack = `${term.term} ${term.assetClass} ${term.definition}`.toLowerCase();
      return haystack.includes(query);
    });

    grid.innerHTML = filtered
      .map(
        (term) => `
          <article class="glossary-card">
            <h3>${escapeHtml(term.term)}</h3>
            <p>${escapeHtml(term.definition)}</p>
            <div class="tag-row">
              <span class="tag">${escapeHtml(term.assetClass)}</span>
            </div>
          </article>
        `,
      )
      .join("");
  };

  input.addEventListener("input", paint);
  paint();
}

function renderMethodology(methodology) {
  byId("methodology-rule").innerHTML = `
    <h3>${escapeHtml(methodology.permanentRule.title)}</h3>
    <p>${escapeHtml(methodology.permanentRule.description)}</p>
    <div class="method-equation">
      ${methodology.permanentRule.labels
        .map(
          (label, index) => `
            ${index > 0 ? '<span class="not-equal">≠</span>' : ""}
            <span class="tag ${escapeHtml(label.kind)}">${escapeHtml(label.name)}</span>
          `,
        )
        .join("")}
    </div>
  `;

  byId("methodology-grid").innerHTML = methodology.sourceHierarchy
    .map(
      (source) => `
        <article class="method-card">
          <span class="method-rank">${escapeHtml(source.rank)}</span>
          <h3>${escapeHtml(source.name)}</h3>
          <p>${escapeHtml(source.useFor)}</p>
          <div class="tag-row">
            ${source.examples.map((example) => `<span class="tag">${escapeHtml(example)}</span>`).join("")}
          </div>
        </article>
      `,
    )
    .join("");
}

function listSection(title, items) {
  if (!items?.length) {
    return "";
  }

  return `
    <section class="briefing-section">
      <h3>${escapeHtml(title)}</h3>
      <ul>${items.map((item) => `<li>${escapeHtml(text(item))}</li>`).join("")}</ul>
    </section>
  `;
}

function textSection(title, value) {
  if (isPlaceholder(value)) {
    return "";
  }

  return `
    <section class="briefing-section">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(text(value))}</p>
    </section>
  `;
}

function briefingSignalsSection(signals) {
  if (!signals?.length) {
    return "";
  }

  return `
    <section class="briefing-section">
      <h3>Dashboard Signals</h3>
      <div class="signals-list">${signals.map((signal) => `
        <article class="signal-card">
          <div class="signal-title">
            <span>${escapeHtml(text(signal.title))}</span>
            <span class="status-chip ${slug(signal.confidence || "pending")}">${escapeHtml(text(signal.confidence))}</span>
          </div>
          <div class="signal-body">
            <div><span class="label">Observation</span>${escapeHtml(text(signal.observation))}</div>
            <div><span class="label">Interpretation</span>${escapeHtml(text(signal.interpretation))}</div>
          </div>
        </article>`).join("")}</div>
    </section>
  `;
}

function briefingMarketSection(section) {
  if (!section?.instrumentIds?.length && isPlaceholder(section?.summary)) {
    return "";
  }

  const instruments = (section.instrumentIds ?? [])
    .map((id) => appState.instruments.get(id))
    .filter(Boolean);

  return `
    <section class="briefing-section">
      <h3>Market Dashboard</h3>
      ${isPlaceholder(section.summary) ? "" : `<p>${escapeHtml(section.summary)}</p>`}
      <div class="briefing-mini-grid">${instruments.map((instrument) => instrumentCard(instrument)).join("")}</div>
    </section>
  `;
}

function briefingDigitalSection(section) {
  if (!section) {
    return "";
  }

  return `
    <section class="briefing-section">
      <h3>Digital Assets</h3>
      <div class="briefing-mini-grid">
        <div class="field-box"><strong>Classification</strong>${escapeHtml(text(section.classification))}</div>
        <div class="field-box"><strong>Summary</strong>${escapeHtml(text(section.summary))}</div>
      </div>
      ${listSection("Macro Drivers", section.macroDrivers ?? [])}
      ${listSection("Crypto-Specific Drivers", section.cryptoSpecificDrivers ?? [])}
    </section>
  `;
}

function briefingCalendarSection(events) {
  if (!events?.length) {
    return "";
  }

  return `
    <section class="briefing-section">
      <h3>Macro Calendar</h3>
      <div class="briefing-mini-grid">
        ${events.map((event) => `
          <div class="field-box">
            <strong>${escapeHtml(text(event.event))}</strong>
            ${escapeHtml(text(event.date))} ${escapeHtml(text(event.time))} ${escapeHtml(text(event.timezone))}
            <br />${escapeHtml(text(event.whyItMatters))}
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function briefingPositioningSection(section) {
  if (!section) {
    return "";
  }

  const hard = section.hardData ?? [];
  const inference = section.marketInference ?? [];
  if (!hard.length && !inference.length) {
    return "";
  }

  return `
    <section class="briefing-section">
      <h3>Positioning / Flows</h3>
      <div class="briefing-mini-grid">
        <div class="field-box"><strong>Hard Data</strong>${hard.map((item) => escapeHtml(text(item.category))).join("<br />") || PLACEHOLDER}</div>
        <div class="field-box"><strong>Market Inference</strong>${inference.map((item) => escapeHtml(text(item.category))).join("<br />") || PLACEHOLDER}</div>
      </div>
    </section>
  `;
}

function briefingScenariosSection(scenarios) {
  if (!scenarios) {
    return "";
  }

  return `
    <section class="briefing-section">
      <h3>Bull / Base / Bear</h3>
      <div class="scenario-grid">
        <div class="field-box"><strong>Bull</strong>${escapeHtml(text(scenarios.bull))}</div>
        <div class="field-box"><strong>Base</strong>${escapeHtml(text(scenarios.base))}</div>
        <div class="field-box"><strong>Bear</strong>${escapeHtml(text(scenarios.bear))}</div>
      </div>
    </section>
  `;
}

function sourcesSection(sources) {
  if (!sources?.length) {
    return "";
  }

  return `
    <section class="briefing-section">
      <h3>Sources</h3>
      <ul class="source-list">
        ${sources
          .map((source) => {
            const href = safeHref(source.url);
            const label = `${text(source.name)} (${text(source.type)})`;
            return href
              ? `<li><a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(label)}</a></li>`
              : `<li>${escapeHtml(label)}</li>`;
          })
          .join("")}
      </ul>
    </section>
  `;
}

function legacySections(sections) {
  if (!sections?.length) {
    return "";
  }

  return sections
    .map(
      (section) => `
        <section class="briefing-section">
          <h3>${escapeHtml(section.title)}</h3>
          <ul>${(section.points ?? []).map((point) => `<li>${escapeHtml(text(point))}</li>`).join("")}</ul>
        </section>
      `,
    )
    .join("");
}

function renderBriefingView(briefing) {
  byId("briefing-view").innerHTML = `
    <p class="eyebrow">${escapeHtml(text(briefing.date))}</p>
    <h3>${escapeHtml(text(briefing.title))}</h3>
    <p>${escapeHtml(text(briefing.summary))}</p>
    ${listSection("Executive Summary", briefing.executiveSummary)}
    ${briefingSignalsSection(briefing.dashboardSignals)}
    ${
      briefing.topMacroStories?.length
        ? `<section class="briefing-section"><h3>Top 5</h3>${normalizeTopStories(briefing.topMacroStories).map(storyCard).join("")}</section>`
        : ""
    }
    ${briefingMarketSection(briefing.marketDashboard)}
    ${briefingDigitalSection(briefing.digitalAssets)}
    ${briefingCalendarSection(briefing.macroCalendar)}
    ${briefingPositioningSection(briefing.positioningFlows)}
    ${textSection("Cross-Asset Narrative", briefing.crossAssetNarrative)}
    ${listSection("Concepts Learned", briefing.conceptsLearned)}
    ${listSection("What to Watch Tomorrow", briefing.whatToWatchTomorrow)}
    ${briefingScenariosSection(briefing.scenarios)}
    ${sourcesSection(briefing.sources)}
    ${legacySections(briefing.sections)}
  `;
}

function renderArchive(archive) {
  const list = byId("archive-list");
  const view = byId("briefing-view");

  const loadBriefing = async (item, selectedButton) => {
    document.querySelectorAll(".archive-item").forEach((button) => button.classList.remove("active"));
    selectedButton.classList.add("active");

    view.innerHTML = `
      <p class="eyebrow">Selected briefing</p>
      <h3>${escapeHtml(item.title)}</h3>
      <p>Loading ${escapeHtml(item.date)}...</p>
    `;

    try {
      renderBriefingView(await getJson(item.path));
    } catch (error) {
      view.innerHTML = `
        <p class="eyebrow">Selected briefing</p>
        <h3>${escapeHtml(item.title)}</h3>
        <p>Unable to load this briefing file.</p>
      `;
    }
  };

  list.innerHTML = archive.items
    .map(
      (item, index) => `
        <button class="archive-item" type="button" data-index="${index}">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.date)} - ${escapeHtml(item.summary)}</span>
        </button>
      `,
    )
    .join("");

  list.querySelectorAll(".archive-item").forEach((button) => {
    button.addEventListener("click", () => {
      loadBriefing(archive.items[Number(button.dataset.index)], button);
    });
  });

  const firstButton = list.querySelector(".archive-item");
  if (firstButton) {
    loadBriefing(archive.items[0], firstButton);
  }
}

async function init() {
  try {
    const [marketData, archive, history] = await Promise.all([
      getJson(DATA_URL),
      getJson(ARCHIVE_URL),
      getJson(HISTORY_URL),
    ]);

    appState.instruments = new Map(marketData.instruments.map((instrument) => [instrument.id, instrument]));

    renderDataStatus(marketData.metadata);
    renderToday(marketData.today);
    renderMarketDashboard(marketData.marketDashboardGroups);
    renderAssetBoards(marketData.assetClassBoards);
    renderCalendar(marketData.calendar);
    renderPositioning(marketData.positioningFlows);
    renderDigitalAssets(marketData.digitalAssets);
    renderGlossary(marketData.glossary);
    renderMethodology(marketData.methodology);
    renderCharts(history);
    renderArchive(archive);

    const currentPath = marketData.today?.currentBriefingPath ?? archive.items?.[0]?.path;
    const currentBriefing = currentPath ? await getJson(currentPath) : {};
    renderTopStories(currentBriefing.topMacroStories ?? []);
  } catch (error) {
    document.body.insertAdjacentHTML(
      "afterbegin",
      `<div class="load-error">Dashboard data could not be loaded. ${escapeHtml(error.message)}</div>`,
    );
  }
}

init();

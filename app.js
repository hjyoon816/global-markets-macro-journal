const DATA_URL = "data/market-data.json";
const ARCHIVE_URL = "data/archive.json";
const PLACEHOLDER = "—";

const byId = (id) => document.getElementById(id);

const isPlaceholder = (value) =>
  value === undefined || value === null || value === "" || value === PLACEHOLDER;

const text = (value) => (isPlaceholder(value) ? PLACEHOLDER : String(value));

const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

function metricValue(value) {
  const className = isPlaceholder(value) ? "metric-value placeholder" : "metric-value";
  return `<span class="${className}">${escapeHtml(text(value))}</span>`;
}

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Unable to load ${url}`);
  }
  return response.json();
}

function renderToday(today, asOf) {
  byId("as-of-pill").textContent = `As of ${text(asOf)}`;

  byId("today-focus-list").innerHTML = today.focus
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
}

function renderRegimeMap(items) {
  byId("regime-map").innerHTML = items
    .map((item) => {
      const level = Number.isFinite(item.level) ? Math.max(0, Math.min(100, item.level)) : 0;
      const bar = level > 0 ? `<span style="width: ${level}%"></span>` : "";

      return `
        <article class="regime-cell">
          <div class="regime-label">
            <span>${escapeHtml(item.label)}</span>
            <span class="regime-value">${escapeHtml(text(item.value))}</span>
          </div>
          <div class="mini-track" aria-hidden="true">
            ${bar}
          </div>
        </article>
      `;
    })
    .join("");
}

function renderRegions(regions) {
  byId("region-grid").innerHTML = regions
    .map(
      (region) => `
        <article class="region-panel">
          <div class="region-header">
            <p class="eyebrow">${escapeHtml(region.kicker)}</p>
            <h3>${escapeHtml(region.title)}</h3>
            <p>${escapeHtml(region.description)}</p>
          </div>
          <ul class="region-list">
            ${region.tiles
              .map(
                (tile) => `
                  <li>
                    <span><strong>${escapeHtml(tile.label)}</strong><br />${escapeHtml(tile.note)}</span>
                    ${metricValue(tile.value)}
                  </li>
                `,
              )
              .join("")}
          </ul>
        </article>
      `,
    )
    .join("");
}

function renderAssetBoards(sections) {
  byId("asset-board").innerHTML = sections
    .map(
      (section) => `
        <article class="asset-panel" id="${escapeHtml(section.id)}">
          <div class="asset-header">
            <h3>${escapeHtml(section.title)}</h3>
            <p>${escapeHtml(section.description)}</p>
          </div>
          <ul class="metric-list">
            ${section.instruments
              .map(
                (instrument) => `
                  <li title="${escapeHtml(instrument.note)}">
                    <span class="metric-name">${escapeHtml(instrument.name)}</span>
                    ${metricValue(instrument.value)}
                  </li>
                `,
              )
              .join("")}
          </ul>
        </article>
      `,
    )
    .join("");
}

function renderDigitalAssets(digitalAssets) {
  byId("digital-metrics").innerHTML = digitalAssets.indicators
    .map(
      (indicator) => `
        <article class="metric-card">
          <span class="label">${escapeHtml(indicator.label)}</span>
          <div class="value ${isPlaceholder(indicator.value) ? "placeholder" : ""}">
            ${escapeHtml(text(indicator.value))}
          </div>
          <p class="note">${escapeHtml(indicator.note)}</p>
        </article>
      `,
    )
    .join("");

  byId("digital-watch-list").innerHTML = digitalAssets.watchFramework
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
}

function renderCalendar(events) {
  byId("calendar-body").innerHTML = events
    .map(
      (event) => `
        <tr>
          <td>${escapeHtml(text(event.date))}</td>
          <td>${escapeHtml(text(event.time))}</td>
          <td>${escapeHtml(text(event.region))}</td>
          <td>${escapeHtml(text(event.event))}</td>
          <td>${escapeHtml(text(event.importance))}</td>
          <td>${escapeHtml(text(event.actual))}</td>
          <td>${escapeHtml(text(event.consensus))}</td>
          <td>${escapeHtml(text(event.previous))}</td>
        </tr>
      `,
    )
    .join("");
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

function renderMethodology(sourceHierarchy) {
  byId("methodology-grid").innerHTML = sourceHierarchy
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
      const briefing = await getJson(item.path);
      view.innerHTML = `
        <p class="eyebrow">${escapeHtml(briefing.date)}</p>
        <h3>${escapeHtml(briefing.title)}</h3>
        <p>${escapeHtml(briefing.summary)}</p>
        ${briefing.sections
          .map(
            (section) => `
              <section class="briefing-section">
                <h3>${escapeHtml(section.title)}</h3>
                <ul>
                  ${section.points.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}
                </ul>
              </section>
            `,
          )
          .join("")}
      `;
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
    const [marketData, archive] = await Promise.all([getJson(DATA_URL), getJson(ARCHIVE_URL)]);
    renderToday(marketData.today, marketData.asOf);
    renderRegimeMap(marketData.regimeMap);
    renderRegions(marketData.regionalDashboards);
    renderAssetBoards(marketData.sections);
    renderDigitalAssets(marketData.digitalAssets);
    renderCalendar(marketData.calendar);
    renderGlossary(marketData.glossary);
    renderMethodology(marketData.sourceHierarchy);
    renderArchive(archive);
  } catch (error) {
    document.body.insertAdjacentHTML(
      "afterbegin",
      `<div class="load-error">Dashboard data could not be loaded. ${escapeHtml(error.message)}</div>`,
    );
  }
}

init();

/* explore_data — client.
 *
 * One rule runs through this file: issue text is data written by strangers.
 * It reaches the DOM only through textContent or a node this file builds, so
 * there is no path from a snapshot body to innerHTML. The markdown renderer
 * below parses into nodes for exactly that reason.
 */

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, kids = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of [].concat(kids)) {
    if (kid) node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

const fmt = new Intl.NumberFormat();
const pct = (n, d) => (d ? Math.round((1000 * n) / d) / 10 : 0);

/* ---------------------------------------------------------------- state */

const MULTI = ["repo", "state", "type", "effort", "author"];
const SCALAR = ["q", "from", "to", "number_min", "number_max", "min_chars", "max_chars", "label"];

const state = {
  split: "dev",
  view: "browse",
  sort: "created_desc",
  selected: null,
  rendered: null,
  shown: 50,
  filters: Object.fromEntries([...MULTI.map((k) => [k, []]), ...SCALAR.map((k) => [k, ""])]),
  table: false,
  meta: null,
  order: [],
  sealedAccepted: new Set(),
};

function queryString(extra = {}) {
  const p = new URLSearchParams({ split: state.split });
  for (const k of MULTI) for (const v of state.filters[k]) p.append(k, v);
  for (const k of SCALAR) if (state.filters[k]) p.set(k, state.filters[k]);
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p.toString();
}

function saveHash() {
  const p = new URLSearchParams(queryString({ sort: state.sort, view: state.view }));
  if (state.selected) p.set("at", state.selected);
  if (state.table) p.set("table", "1");
  history.replaceState(null, "", "#" + p.toString());
}

function loadHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (!p.toString()) return;
  state.split = p.get("split") || state.split;
  state.sort = p.get("sort") || state.sort;
  state.view = p.get("view") === "stats" ? "stats" : "browse";
  state.selected = p.get("at");
  state.table = p.get("table") === "1";
  for (const k of MULTI) state.filters[k] = p.getAll(k);
  for (const k of SCALAR) state.filters[k] = p.get(k) || "";
}

async function api(path, extra = {}) {
  const res = await fetch(`/api/${path}?${queryString(extra)}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

/* ------------------------------------------------------- safe markdown */

function withHighlight(text, query) {
  const frag = document.createDocumentFragment();
  if (!query) {
    frag.append(document.createTextNode(text));
    return frag;
  }
  const lower = text.toLowerCase();
  let at = 0;
  for (;;) {
    const hit = lower.indexOf(query, at);
    if (hit < 0) break;
    frag.append(document.createTextNode(text.slice(at, hit)));
    frag.append(el("mark", { text: text.slice(hit, hit + query.length) }));
    at = hit + query.length;
  }
  frag.append(document.createTextNode(text.slice(at)));
  return frag;
}

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(!\[[^\]]*\]\([^)\s]+\))|(\[[^\]]*\]\([^)\s]+\))|(https?:\/\/[^\s<>)\]]+)/g;

function inlineInto(parent, text, query) {
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) parent.append(withHighlight(text.slice(last, m.index), query));
    const tok = m[0];
    if (tok.startsWith("`")) {
      parent.append(el("code", { text: tok.slice(1, -1) }));
    } else if (tok.startsWith("**")) {
      parent.append(el("strong", {}, [withHighlight(tok.slice(2, -2), query)]));
    } else if (tok.startsWith("![")) {
      const alt = tok.slice(2, tok.indexOf("]"));
      // Remote images are never loaded: this is a local reader and the URLs
      // belong to strangers. The reference is shown as text instead.
      parent.append(el("span", { class: "imgref", text: `🖼 image${alt ? ": " + alt : ""}` }));
    } else if (tok.startsWith("[")) {
      const label = tok.slice(1, tok.indexOf("]"));
      const href = tok.slice(tok.indexOf("](") + 2, -1);
      parent.append(safeLink(href, label || href, query));
    } else {
      parent.append(safeLink(tok, tok, query));
    }
    last = m.index + tok.length;
  }
  if (last < text.length) parent.append(withHighlight(text.slice(last), query));
}

function safeLink(href, label, query) {
  // Only http(s) becomes a link; anything else stays inert text.
  if (!/^https?:\/\//i.test(href)) return el("span", { text: label });
  return el("a", { href, target: "_blank", rel: "noopener noreferrer nofollow" }, [
    withHighlight(label, query),
  ]);
}

function renderMarkdown(text, query) {
  const root = el("div", { class: "body" });
  const lines = String(text || "").split(/\r?\n/);
  let i = 0;
  let list = null;

  const flushList = () => { list = null; };

  while (i < lines.length) {
    const line = lines[i];

    // fenced code
    const fence = line.match(/^\s*```+\s*([\w+-]*)/);
    if (fence) {
      flushList();
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      const pre = el("pre", {}, [el("code", { text: buf.join("\n") })]);
      if (fence[1]) pre.dataset.lang = fence[1];
      root.append(pre);
      continue;
    }

    // html comments (issue templates are full of them; they matter here
    // because a reader never sees them on github)
    if (line.includes("<!--")) {
      flushList();
      const buf = [line];
      while (i < lines.length && !lines[i].includes("-->")) buf.push(lines[++i] ?? "");
      i++;
      const raw = buf.join("\n").replace(/<!--/g, "").replace(/-->/g, "").trim();
      root.append(el("span", { class: "comment", text: "hidden comment · " + raw }));
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushList();
      const tag = "h" + Math.min(heading[1].length + 1, 4);
      const node = el(tag);
      inlineInto(node, heading[2], query);
      root.append(node);
      i++;
      continue;
    }

    if (/^\s*([-*_])\s*\1\s*\1[\s-*_]*$/.test(line)) {
      flushList();
      root.append(el("hr"));
      i++;
      continue;
    }

    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushList();
      const node = el("blockquote");
      inlineInto(node, quote[1], query);
      root.append(node);
      i++;
      continue;
    }

    const item = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.*)$/);
    if (item) {
      const ordered = /^\s*\d/.test(line);
      if (!list || list.tagName !== (ordered ? "OL" : "UL")) {
        list = el(ordered ? "ol" : "ul");
        root.append(list);
      }
      const li = el("li");
      inlineInto(li, item[1], query);
      list.append(li);
      i++;
      continue;
    }

    if (!line.trim()) {
      flushList();
      i++;
      continue;
    }

    // paragraph: join until a blank line
    flushList();
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|>|[-*+]\s|\d+[.)]\s|<!--)/.test(lines[i])) {
      buf.push(lines[i++]);
    }
    const p = el("p");
    inlineInto(p, buf.join(" "), query);
    root.append(p);
  }

  if (!root.childNodes.length) root.append(el("p", { class: "empty", text: "(empty body)" }));
  return root;
}

/* ------------------------------------------------------------ filters */

function checkGroup(host, name, values, counts) {
  host.replaceChildren();
  for (const value of values) {
    const checked = state.filters[name].includes(value);
    const box = el("input", { type: "checkbox", checked });
    box.addEventListener("change", () => {
      const set = new Set(state.filters[name]);
      box.checked ? set.add(value) : set.delete(value);
      state.filters[name] = [...set];
      refresh();
    });
    host.append(
      el("label", { class: "chk" }, [
        box,
        el("span", { text: value }),
        el("span", { class: "n", id: `n-${name}-${value}`, text: counts?.[value] ?? "" }),
      ])
    );
  }
}

async function splitCounts() {
  // Counts beside each checkbox describe the whole split, not the current
  // selection: they are a map of what is there, and they must not move when
  // the filter moves.
  const res = await fetch(`/api/stats?split=${encodeURIComponent(state.split)}`);
  if (!res.ok) return;
  const { charts } = await res.json();
  for (const [name, rows] of Object.entries({
    repo: charts.repo, state: charts.state, type: charts.type,
    effort: charts.effort, author: charts.author,
  })) {
    for (const row of rows || []) {
      const cell = document.getElementById(`n-${name}-${row.key}`);
      if (cell) cell.textContent = fmt.format(row.count);
    }
  }
}

function bindScalar(id, delay = 250) {
  const input = $(id);
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.filters[id] = input.value.trim();
      refresh();
    }, delay);
  });
}

function syncInputs() {
  for (const k of SCALAR) if ($(k)) $(k).value = state.filters[k];
  $("sort").value = state.sort;
}

/* --------------------------------------------------------------- list */

function issueRow(item) {
  const key = `${item.repo}#${item.number}`;
  const row = el("button", { class: "item", "aria-current": state.selected === key }, [
    el("span", { class: "t", text: item.title || "(no title)" }),
    el("span", { class: "m" }, [
      el("span", { text: key }),
      el("span", { text: item.created_at.slice(0, 10) }),
      el("span", { text: item.state }),
      item.gold_type
        ? el("span", { style: "color:var(--series-1)", text: item.gold_type })
        : el("span", { text: "unlabelled" }),
    ]),
  ]);
  row.addEventListener("click", () => selectIssue(key));
  return row;
}

async function renderList() {
  const data = await api("issues", { sort: state.sort, limit: state.shown, offset: 0 });
  state.order = data.order;
  $("list-count").textContent = `${fmt.format(data.total)} issue${data.total === 1 ? "" : "s"}`;
  $("count").textContent = `${fmt.format(data.total)} of ${fmt.format(state.meta?.facets?.count ?? 0)} selected`;

  const list = $("list");
  list.replaceChildren();
  if (!data.items.length) {
    list.append(el("div", { class: "empty", text: "No issue matches these filters." }));
    return;
  }
  for (const item of data.items) list.append(issueRow(item));
  if (data.total > data.items.length) {
    list.append(
      el("button", {
        class: "more",
        text: `show ${Math.min(50, data.total - data.items.length)} more of ${fmt.format(data.total)}`,
        onclick: () => { state.shown += 50; renderList(); },
      })
    );
  }
  // An `at=` deep link names an issue the reader has not drawn yet; a plain
  // visit falls back to the first row of the current filter.
  if (state.selected && state.rendered !== state.selected) selectIssue(state.selected);
  else if (!state.selected && data.items.length) selectIssue(`${data.items[0].repo}#${data.items[0].number}`);
}

/* ------------------------------------------------------------- reader */

function signalChips(signals) {
  const out = [
    ["chars", fmt.format(signals.body_chars)],
    ["words", fmt.format(signals.body_words)],
    ["code blocks", signals.code_blocks],
    ["template sections", signals.template_sections],
    ["checkboxes", signals.checkboxes],
  ];
  if (signals.has_traceback) out.push(["traceback", "yes"]);
  if (signals.has_images) out.push(["images", "yes"]);
  if (signals.non_ascii_ratio > 0.05) out.push(["non-ascii", `${Math.round(signals.non_ascii_ratio * 100)}%`]);
  return out;
}

async function selectIssue(key) {
  state.selected = key;
  saveHash();
  for (const node of document.querySelectorAll(".item")) node.removeAttribute("aria-current");
  const [repo, number] = key.split("#");
  const issue = await api("issue", { repo, number });

  const at = state.order.indexOf(key);
  const nav = el("div", { class: "nav" }, [
    el("button", {
      class: "ghost", text: "← prev", disabled: at <= 0,
      onclick: () => selectIssue(state.order[at - 1]),
    }),
    el("button", {
      class: "ghost", text: "next →", disabled: at < 0 || at >= state.order.length - 1,
      onclick: () => selectIssue(state.order[at + 1]),
    }),
    el("span", { text: at >= 0 ? `${at + 1} of ${fmt.format(state.order.length)} in this filter` : "" }),
  ]);

  const gold = Object.entries(issue.gold);
  const present = gold.filter(([, v]) => v !== null && v !== undefined);

  const inner = el("div", { class: "reader-inner" }, [
    nav,
    el("h1", {}, [withHighlight(issue.title || "(no title)", state.filters.q.toLowerCase())]),
    el("div", { class: "meta" }, [
      el("span", { class: "chip k", text: `${issue.repo} #${issue.number}` }),
      el("span", { class: `chip state ${issue.state}`, text: issue.state }),
      el("span", { class: "chip", text: `opened ${issue.created_at.slice(0, 10)}` }),
      issue.closed_at ? el("span", { class: "chip", text: `closed after ${issue.days_to_close}d` }) : null,
      el("span", { class: "chip", text: `${issue.comments} comment${issue.comments === 1 ? "" : "s"}` }),
      el("span", { class: "chip", text: `author: ${issue.author_association.toLowerCase() || "?"}` }),
      el("span", { class: `chip eff ${issue.signals.effort}`, text: `${issue.signals.effort} effort` }),
      issue.url ? el("a", { class: "chip", href: issue.url, target: "_blank", rel: "noopener noreferrer", text: "github ↗" }) : null,
    ]),

    el("div", { class: "panel" }, [
      el("h3", { text: "Labels on github" }),
      el("div", { class: "meta", style: "margin:0" },
        issue.labels.length
          ? issue.labels.map((l) => el("span", { class: "chip k", text: l }))
          : [el("span", { class: "chip none", text: "no labels at all" })]),
    ]),

    el("div", { class: "panel" }, [
      el("h3", { text: `Gold annotation — ${present.length} of ${gold.length} fields present` }),
      el("div", { class: "meta", style: "margin:0" },
        gold.map(([k, v]) =>
          el("span", {
            class: `chip ${v === null || v === undefined ? "none" : "gold"}`,
            text: `${k.replace("gold_", "")}: ${v === null || v === undefined ? "—" : v}`,
          })
        )),
    ]),

    el("div", { class: "panel" }, [
      el("h3", { text: "Reading cost (derived here, not in the data)" }),
      el("div", { class: "kv" },
        signalChips(issue.signals).map(([k, v]) =>
          el("div", {}, [el("b", { text: String(v) }), k]))),
    ]),

    renderMarkdown(issue.body, state.filters.q.toLowerCase()),
  ]);

  const reader = $("reader");
  reader.replaceChildren(inner);
  state.rendered = key;
  reader.scrollTop = 0;
  const active = [...document.querySelectorAll(".item")].find((n) => n.textContent.includes(key));
  if (active) active.setAttribute("aria-current", "true");
}

/* -------------------------------------------------------------- charts */

const tip = () => $("tip");

function hoverable(node, lines) {
  node.addEventListener("mousemove", (e) => {
    const t = tip();
    t.replaceChildren(...lines.map((l) => el("div", {}, [l])));
    t.classList.add("on");
    const pad = 14;
    t.style.left = Math.min(e.clientX + pad, window.innerWidth - t.offsetWidth - 8) + "px";
    t.style.top = Math.min(e.clientY + pad, window.innerHeight - t.offsetHeight - 8) + "px";
  });
  node.addEventListener("mouseleave", () => tip().classList.remove("on"));
  return node;
}

function toggleFilter(name, value) {
  const set = new Set(state.filters[name]);
  set.has(value) ? set.delete(value) : set.add(value);
  state.filters[name] = [...set];
  refresh();
}

function barCard(title, sub, rows, total, opts = {}) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  const bars = el("div", { class: "bars" });
  for (const row of rows) {
    const on = opts.filter ? state.filters[opts.filter].includes(row.key) : false;
    const bar = el("div", { class: `bar${on ? " on" : ""}${opts.filter ? "" : " static"}` }, [
      el("div", { class: "lbl", title: row.key, text: row.key }),
      el("div", { class: "track" }, [
        el("div", { class: "fill", style: `width:${(100 * row.count) / max}%` }),
      ]),
      el("div", { class: "val", text: `${fmt.format(row.count)}  ${pct(row.count, total)}%` }),
    ]);
    hoverable(bar, [
      el("b", { text: row.key }),
      `${fmt.format(row.count)} of ${fmt.format(total)} (${pct(row.count, total)}%)`,
      opts.filter ? el("span", { class: "k", text: on ? "click to remove filter" : "click to filter" }) : null,
    ].filter(Boolean));
    if (opts.filter) bar.addEventListener("click", () => toggleFilter(opts.filter, row.key));
    bars.append(bar);
  }
  return el("div", { class: "card" }, [
    el("h3", { text: title }),
    el("div", { class: "sub", text: sub }),
    opts.asTable ? dataTable(rows, total) : bars,
  ]);
}

function dataTable(rows, total) {
  return el("table", { class: "data" }, [
    el("thead", {}, [el("tr", {}, [el("th", { text: "value" }), el("th", { class: "n", text: "count" }), el("th", { class: "n", text: "%" })])]),
    el("tbody", {}, rows.map((r) =>
      el("tr", {}, [el("td", { text: r.key }), el("td", { class: "n", text: fmt.format(r.count) }), el("td", { class: "n", text: pct(r.count, total) + "%" })]))),
  ]);
}

function monthCard(rows, total, asTable) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  const cols = el("div", { class: "cols" });
  for (const row of rows) {
    const on = state.filters.from === row.key + "-01";
    const col = el("div", { class: `col${on ? " on" : ""}` }, [
      el("i", { style: `height:${(100 * row.count) / max}%` }),
    ]);
    hoverable(col, [el("b", { text: row.key }), `${fmt.format(row.count)} issues opened`, el("span", { class: "k", text: "click to filter to this month" })]);
    col.addEventListener("click", () => {
      const [y, m] = row.key.split("-").map(Number);
      const end = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
      state.filters.from = on ? "" : `${row.key}-01`;
      state.filters.to = on ? "" : end;
      syncInputs();
      refresh();
    });
    cols.append(col);
  }
  return el("div", { class: "card" }, [
    el("h3", { text: "Issues opened per month" }),
    el("div", { class: "sub", text: "Click a column to filter to that month." }),
    asTable ? dataTable(rows, total) : el("div", {}, [
      cols,
      el("div", { class: "axis-row" }, [
        el("span", { text: rows[0]?.key ?? "" }),
        el("span", { text: rows[rows.length - 1]?.key ?? "" }),
      ]),
    ]),
  ]);
}

function coverageCard(coverage, asTable) {
  if (asTable) {
    return el("div", { class: "card" }, [
      el("h3", { text: "Gold type coverage by project" }),
      el("table", { class: "data" }, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "project" }), el("th", { class: "n", text: "labelled" }), el("th", { class: "n", text: "unlabelled" }), el("th", { class: "n", text: "%" })])]),
        el("tbody", {}, coverage.map((c) =>
          el("tr", {}, [el("td", { text: c.repo }), el("td", { class: "n", text: c.labelled }), el("td", { class: "n", text: c.unlabelled }), el("td", { class: "n", text: c.percent + "%" })]))),
      ]),
    ]);
  }
  const rows = coverage.map((c) => {
    const stack = el("div", { class: "stack" }, [
      hoverable(el("i", { class: "s1", style: `flex:${Math.max(c.labelled, 0.01)}` }),
        [el("b", { text: `${c.repo}: labelled` }), `${c.labelled} of ${c.total} (${c.percent}%)`]),
      hoverable(el("i", { class: "s2", style: `flex:${Math.max(c.unlabelled, 0.01)}` }),
        [el("b", { text: `${c.repo}: unlabelled` }), `${c.unlabelled} of ${c.total} (${pct(c.unlabelled, c.total)}%)`]),
    ]);
    return el("div", { class: "cov-row" }, [
      el("div", { class: "top" }, [
        el("b", { text: c.repo }),
        el("span", { text: `${c.labelled} labelled · ${c.unlabelled} not · ${c.percent}%` }),
      ]),
      stack,
    ]);
  });
  return el("div", { class: "card" }, [
    el("h3", { text: "Gold type coverage by project" }),
    el("div", { class: "sub", text: "How much of this selection already carries a usable label." }),
    el("div", { class: "legend" }, [
      el("span", {}, [el("i", { class: "s1" }), "has gold_type"]),
      el("span", {}, [el("i", { class: "s2" }), "unlabelled"]),
    ]),
    ...rows,
  ]);
}

function goldFieldsCard(fields, total, asTable) {
  const rows = fields.map((f) => ({ key: f.key, count: f.count }));
  const card = barCard(
    "Which gold fields exist at all",
    `Out of ${fmt.format(total)} selected issues. Empty bars are fields a human would have to create from scratch.`,
    rows, total, { asTable }
  );
  return card;
}

async function renderStats() {
  const data = await api("stats");
  const host = $("stats");
  host.replaceChildren();

  if (!data.total) {
    host.append(el("div", { class: "empty", text: "No issue matches these filters." }));
    return;
  }
  const h = data.headline;
  const c = data.charts;
  const asTable = state.table;

  host.append(
    el("div", { style: "display:flex;align-items:baseline;gap:12px;margin-bottom:14px" }, [
      el("h2", { style: "margin:0;font-size:16px", text: `${fmt.format(data.total)} issues in the current filter` }),
      el("div", { class: "spacer", style: "flex:1" }),
      el("button", {
        class: "ghost",
        text: asTable ? "show charts" : "show as tables",
        onclick: () => { state.table = !state.table; saveHash(); renderStats(); },
      }),
    ])
  );

  const tiles = [
    [fmt.format(h.total), "issues selected", `${h.repos} project${h.repos === 1 ? "" : "s"} · ${h.open_percent}% still open`],
    [`${h.gold_type_percent}%`, "have a gold type", `${fmt.format(Math.round((h.total * (100 - h.gold_type_percent)) / 100))} would need labelling`],
    [`${h.any_label_percent}%`, "have any github label", "the rest offer no maintainer signal at all"],
    [`${h.reading_hours}h`, "to read every body once", `at ${fmt.format(180)} words/min, no judgement time`],
    [fmt.format(h.median_chars), "median body characters", `longest is ${fmt.format(h.max_chars)}`],
    [`${h.templated_percent}%`, "follow an issue template", `${h.with_code_percent}% contain a code block`],
  ];
  host.append(el("div", { class: "tiles" }, tiles.map(([v, l, s]) =>
    el("div", { class: "tile" }, [el("div", { class: "v", text: v }), el("div", { class: "l", text: l }), el("div", { class: "s", text: s })]))));

  const grid = el("div", { class: "grid" });
  grid.append(coverageCard(data.coverage, asTable));
  grid.append(goldFieldsCard(data.gold_fields, data.total, asTable));
  grid.append(barCard("By project", "Click a bar to filter.", c.repo, data.total, { filter: "repo", asTable }));
  grid.append(barCard("By gold type", "“(none)” is an issue no maintainer label resolved.", c.type, data.total, { filter: "type", asTable }));
  grid.append(barCard("By status", "Click a bar to filter.", c.state, data.total, { filter: "state", asTable }));
  grid.append(barCard("By annotation effort", "Derived: length, code, template, labels, language.", c.effort, data.total, { filter: "effort", asTable }));
  grid.append(barCard("By author association", "Who opened it, as github classifies them.", c.author, data.total, { filter: "author", asTable }));
  grid.append(monthCard(c.month, data.total, asTable));
  grid.append(barCard("Body length", "Characters per issue body.", c.body_chars, data.total, { asTable }));
  grid.append(barCard("Comments", "Discussion length is a proxy for how contested the triage was.", c.comments, data.total, { asTable }));
  grid.append(barCard("Top github labels", "Raw labels, per repo vocabularies, not normalised.", c.label, data.total, { asTable }));
  host.append(grid);

  host.append(
    el("div", { class: "card", style: "margin-top:14px" }, [
      el("h3", { text: "How “annotation effort” is computed" }),
      el("div", { class: "sub", text: "A reading-cost proxy, not a measurement. One point each unless noted." }),
      el("ul", { style: "margin:0;padding-left:20px;color:var(--ink-2);font-size:12.5px" }, [
        el("li", { text: "body length: 0 under 600 chars, 1 under 2k, 2 under 6k, 3 above" }),
        el("li", { text: "3 or more code blocks" }),
        el("li", { text: "contains a stack trace" }),
        el("li", { text: "no template headings — free prose is harder to skim" }),
        el("li", { text: "no github labels — nothing to anchor a judgement on" }),
        el("li", { text: "more than 5% non-ascii letters — likely not written in English" }),
        el("li", { text: "0–1 = low, 2–3 = medium, 4+ = high" }),
      ]),
    ])
  );
}

/* ------------------------------------------------------------ refresh */

let pending = null;

function sealedBlocked() {
  return (state.meta?.sealed || []).includes(state.split) && !state.sealedAccepted.has(state.split);
}

function showSealGate() {
  $("seal-banner").hidden = false;
  $("sealed-tag").hidden = false;
  $("count").textContent = "";
  $("list-count").textContent = "—";
  $("list").replaceChildren();
  $("reader").replaceChildren(el("div", { class: "empty", text: "Sealed split — not loaded." }));
  $("stats").replaceChildren(el("div", { class: "empty", text: "Sealed split — not loaded." }));
}

function refresh() {
  state.shown = 50;
  saveHash();
  if (sealedBlocked()) {
    showSealGate();
    return;
  }
  clearTimeout(pending);
  pending = setTimeout(async () => {
    try {
      if (state.view === "browse") await renderList();
      else await renderStats();
      // The counts beside each filter box describe the whole split, so they
      // stay still while the selection moves.
    } catch (error) {
      const host = state.view === "browse" ? $("list") : $("stats");
      host.replaceChildren(el("div", { class: "empty", text: String(error.message || error) }));
    }
  }, 60);
}

async function loadSplit(split) {
  // Only a real split change drops the open issue: at boot this runs with the
  // split the URL already named, and an `at=` deep link has to survive it.
  if (split !== state.split) state.selected = null;
  state.split = split;
  $("sealed-tag").hidden = !state.meta?.sealed?.includes(split);
  if (sealedBlocked()) {
    showSealGate();
    return;
  }
  $("seal-banner").hidden = true;
  const meta = await api("meta");
  state.meta = { ...state.meta, ...meta };
  const f = meta.facets;
  checkGroup($("f-repo"), "repo", f.repo);
  checkGroup($("f-state"), "state", f.state);
  checkGroup($("f-type"), "type", f.type);
  checkGroup($("f-effort"), "effort", f.effort);
  checkGroup($("f-author"), "author", f.author);
  $("from").min = $("to").min = f.date_min;
  $("from").max = $("to").max = f.date_max;
  $("number_min").placeholder = `min ${f.number_min}`;
  $("number_max").placeholder = `max ${f.number_max}`;
  const label = $("label");
  label.replaceChildren(el("option", { value: "", text: `any (${f.label.length} distinct)` }));
  for (const name of f.label) label.append(el("option", { value: name, text: name }));
  label.value = state.filters.label;
  splitCounts();
  $("subtitle").textContent = `data/snapshot/${split}.json · ${fmt.format(f.count)} issues`;
  refresh();
}

function setView(view) {
  state.view = view;
  $("tab-browse").setAttribute("aria-selected", view === "browse");
  $("tab-stats").setAttribute("aria-selected", view === "stats");
  $("view-browse").hidden = view !== "browse";
  $("view-stats").hidden = view !== "stats";
  refresh();
}

/* --------------------------------------------------------------- boot */

async function boot() {
  loadHash();
  const meta = await api("meta");
  state.meta = meta;
  const select = $("split");
  select.replaceChildren(...meta.splits.map((s) =>
    el("option", { value: s.name, text: `${s.name}${s.sealed ? " (sealed)" : ""} · ${Math.round(s.bytes / 1024)} KB` })));
  if (!meta.splits.some((s) => s.name === state.split)) state.split = meta.splits[0].name;
  select.value = state.split;
  select.addEventListener("change", () => loadSplit(select.value));

  $("seal-ok").addEventListener("click", () => {
    state.sealedAccepted.add(state.split);
    loadSplit(state.split);
  });
  $("tab-browse").addEventListener("click", () => setView("browse"));
  $("tab-stats").addEventListener("click", () => setView("stats"));
  $("sort").addEventListener("change", () => { state.sort = $("sort").value; refresh(); });
  $("label").addEventListener("change", () => { state.filters.label = $("label").value; refresh(); });
  $("reset").addEventListener("click", () => {
    for (const k of MULTI) state.filters[k] = [];
    for (const k of SCALAR) state.filters[k] = "";
    syncInputs();
    loadSplit(state.split);
  });
  $("theme").addEventListener("click", () => {
    const now = document.documentElement.getAttribute("data-theme");
    const next = now === "dark" ? "light" : now === "light" ? "" : "dark";
    next ? document.documentElement.setAttribute("data-theme", next)
         : document.documentElement.removeAttribute("data-theme");
  });

  bindScalar("q");
  for (const id of ["from", "to", "number_min", "number_max", "min_chars", "max_chars"]) bindScalar(id, 350);
  syncInputs();

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea")) return;
    const at = state.order.indexOf(state.selected);
    if ((e.key === "j" || e.key === "ArrowDown") && at < state.order.length - 1) { e.preventDefault(); selectIssue(state.order[at + 1]); }
    if ((e.key === "k" || e.key === "ArrowUp") && at > 0) { e.preventDefault(); selectIssue(state.order[at - 1]); }
    if (e.key === "/") { e.preventDefault(); $("q").focus(); }
  });

  setView(state.view);
  await loadSplit(state.split);
}

boot();

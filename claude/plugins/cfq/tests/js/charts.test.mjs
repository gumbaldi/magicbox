// Tests for portal/charts.js: slots, scale, the three SVG charts, legend and numbers table.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fakeDoc, fakeRoot, findAll, byTag, collectText, loadPortal } from "./helpers.mjs";

const CFQ = loadPortal();
const K = CFQ.charts;

// SVG nodes carry their class as an attribute (`className` is read-only on real SVG elements).
const svgClass = (n) => (n.attrs && n.attrs.class ? n.attrs.class.split(/\s+/) : []);
const bySvg = (node, tag, cls) => findAll(node, (n) => n.tagName === tag && (!cls || svgClass(n).includes(cls)));
const num = (n, k) => Number(n.attrs[k]);

test("modelSlots: sorted names map to m0..m5, later ones share m-other, deterministic", () => {
  const names = ["g", "b", "a", "f", "e", "d", "c", "h"];
  const slots = K.modelSlots(names);
  assert.deepEqual(slots, { a: "m0", b: "m1", c: "m2", d: "m3", e: "m4", f: "m5", g: "m-other", h: "m-other" });
  assert.deepEqual(K.modelSlots([...names].reverse()), slots);
  assert.deepEqual(K.modelSlots(["x", "x", "a"]), { a: "m0", x: "m1" });
  assert.deepEqual(K.modelSlots([]), {});
});

test("scaleMax: 1, 2 or 5 times a power of ten, at or above the maximum", () => {
  assert.equal(K.scaleMax([]), 1);
  assert.equal(K.scaleMax([0, 0]), 1);
  assert.equal(K.scaleMax([1]), 1);
  assert.equal(K.scaleMax([3]), 5);
  assert.equal(K.scaleMax([7, 2]), 10);
  assert.equal(K.scaleMax([1000]), 1000);
  assert.equal(K.scaleMax([1001]), 2000);
  assert.equal(K.scaleMax([120000]), 200000);
  assert.equal(K.scaleMax([1500000]), 2000000);
  assert.equal(K.scaleMax([0.3]), 0.5);
  for (const v of [1, 4.9, 20, 55, 999, 12345, 987654]) assert.ok(K.scaleMax([v]) >= v);
});

const slots = K.modelSlots(["claude-haiku-5", "claude-sonnet-5-5"]);

test("stackedBars: one group per bar, one rect per non-zero key, heights proportional", () => {
  const doc = fakeDoc();
  const bars = [
    { label: "bar one", tick: "1", href: "#/batch/one", values: { "claude-sonnet-5-5": 600, "claude-haiku-5": 200 } },
    { label: "bar two", tick: "2", href: "#/batch/two", values: { "claude-sonnet-5-5": 300, "claude-haiku-5": 0 } },
  ];
  const svg = K.stackedBars(doc, { bars, keys: slots, metric: "Output tokens" });
  assert.equal(svg.tagName, "svg");
  assert.equal(svg.namespaceURI, "http://www.w3.org/2000/svg");
  const groups = bySvg(svg, "g", "bar");
  assert.equal(groups.length, 2);
  assert.deepEqual(groups.map((gr) => bySvg(gr, "rect").length), [2, 1]);

  const max = K.scaleMax([800, 300]);
  const rects = bySvg(groups[0], "rect");
  const heights = rects.map((r) => num(r, "height"));
  // sonnet (m1) has three times the height of haiku (m0); slot order puts m0 at the bottom
  assert.deepEqual(rects.map(svgClass), [["m0"], ["m1"]]);
  assert.ok(Math.abs(heights[1] / heights[0] - 3) < 0.05);
  // the bar total against the scale maximum: the top grid line is `max`, so the stack is total/max of it
  const top = bySvg(svg, "line", "grid").map((l) => num(l, "y1")).sort((a, b) => a - b)[0];
  const base = num(bySvg(svg, "line", "axis")[0], "y1");
  const stackH = heights.reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(stackH - ((800 / max) * (base - top))) < 0.1);
  const lone = bySvg(groups[1], "rect")[0];
  assert.ok(Math.abs(num(lone, "height") - ((300 / max) * (base - top))) < 0.05);
});

test("stackedBars: links and exact per-model titles; no data returns null", () => {
  const doc = fakeDoc();
  const svg = K.stackedBars(doc, {
    bars: [{ label: "bar one", tick: "1", href: "#/batch/one", values: { "claude-sonnet-5-5": 1234567, "claude-haiku-5": 89 } }],
    keys: slots, metric: "Output tokens",
  });
  const a = bySvg(svg, "a");
  assert.equal(a.length, 1);
  assert.equal(a[0].attrs.href, "#/batch/one");
  const title = bySvg(a[0], "title")[0].textContent;
  assert.match(title, /^bar one\n/);
  assert.ok(title.includes("claude-sonnet-5-5: " + (1234567).toLocaleString()));
  assert.ok(title.includes("claude-haiku-5: " + (89).toLocaleString()));
  assert.ok(title.includes("total: " + (1234656).toLocaleString()));

  assert.equal(K.stackedBars(doc, { bars: [], keys: slots, metric: "x" }), null);
  assert.equal(K.stackedBars(doc, { bars: [{ label: "z", values: { "claude-haiku-5": 0 } }], keys: slots, metric: "x" }), null);
  const plain = K.stackedBars(doc, { bars: [{ label: "p", values: { "claude-haiku-5": 5 } }], keys: slots, metric: "x" });
  assert.equal(bySvg(plain, "a").length, 0, "no href, no link");
});

test("hBars: one row per entry, widths proportional to the largest total", () => {
  const doc = fakeDoc();
  const rows = [
    { label: "big", href: "#/batch/big", values: { "claude-sonnet-5-5": 300, "claude-haiku-5": 100 } },
    { label: "small", values: { "claude-sonnet-5-5": 100 } },
  ];
  const svg = K.hBars(doc, rows, slots);
  const groups = bySvg(svg, "g", "row");
  assert.equal(groups.length, 2);
  const widths = (gr) => bySvg(gr, "rect").map((r) => num(r, "width"));
  const [bigW, smallW] = [widths(groups[0]), widths(groups[1])];
  assert.deepEqual(bySvg(groups[0], "rect").map(svgClass), [["m0"], ["m1"]]);
  assert.ok(Math.abs(bigW[0] / bigW[1] - 1 / 3) < 0.02);
  assert.ok(Math.abs((bigW[0] + bigW[1]) / smallW[0] - 4) < 0.05);
  assert.equal(K.hBars(doc, [], slots), null);
  assert.equal(K.hBars(doc, [{ label: "z", values: {} }], slots), null);
});

test("stripBySize: a column per size, a dot per point, median line, label and small-sample note", () => {
  const doc = fakeDoc();
  const points = [
    { batch: "b1", phase: "01-a", size: "S", turns: 10, output: 1000 },
    { batch: "b1", phase: "02-b", size: "S", turns: 30, output: 3000 },
    { batch: "b2", phase: "01-a", size: "M", turns: 50, output: 9000 },
  ];
  const baselines = { S: { n: 5, turnsMedian: 20, outputMedian: 2000 }, M: { n: 1, turnsMedian: 50, outputMedian: 9000 } };
  const svg = K.stripBySize(doc, { points, baselines, metric: "turns" });
  const columns = bySvg(svg, "g", "column");
  assert.equal(columns.length, 2);
  assert.deepEqual(columns.map((c) => bySvg(c, "circle", "dot").length), [2, 1]);
  assert.deepEqual(columns.map((c) => bySvg(c, "line", "median").length), [1, 1]);
  const labels = columns.map((c) => bySvg(c, "text", "median-label")[0].textContent);
  assert.deepEqual(labels, ["median 20 · n=5", "median 50 · n=1"]);
  assert.deepEqual(columns.map((c) => bySvg(c, "text", "note").length), [0, 1]);
  assert.equal(bySvg(columns[1], "text", "note")[0].textContent, "outlier check needs 5");

  const out = K.stripBySize(doc, { points, baselines, metric: "output" });
  assert.deepEqual(bySvg(out, "text", "median-label").map((t) => t.textContent), ["median 2k · n=5", "median 9k · n=1"]);

  // median line height follows the value
  const medY = (c) => num(bySvg(c, "line", "median")[0], "y1");
  assert.ok(medY(columns[1]) < medY(columns[0]), "50 sits above 20");
  assert.equal(K.stripBySize(doc, { points: [], baselines, metric: "turns" }), null);
  const noBase = K.stripBySize(doc, { points: [points[0]], baselines: {}, metric: "turns" });
  assert.equal(bySvg(noBase, "line", "median").length, 0);
  assert.equal(bySvg(noBase, "text", "median-label")[0].textContent, "median – · n=0");
});

test("legend: every model name as text beside its swatch", () => {
  const doc = fakeDoc();
  const ul = K.legend(doc, slots);
  const items = byTag(ul, "li");
  assert.equal(items.length, 2);
  assert.match(collectText(ul), /claude-haiku-5/);
  assert.match(collectText(ul), /claude-sonnet-5-5/);
  const swatch = findAll(items[0], (n) => n.className && n.className.startsWith("swatch"))[0];
  assert.equal(swatch.className, "swatch m0");
  assert.equal(swatch.attrs["aria-hidden"], "true");
});

test("numbersTable: exact, unrounded values", () => {
  const doc = fakeDoc();
  const table = K.numbersTable(doc, [{ key: "name", label: "Name" }, { key: "v", label: "Value", num: true }],
    [{ name: "a", v: 1234567 }, { name: "b", v: 0 }, { name: "c" }]);
  const cells = byTag(table, "td").map((t) => t.textContent);
  assert.deepEqual(cells, ["a", "1234567", "b", "0", "c", "–"]);
  assert.deepEqual(byTag(table, "th").map((t) => t.textContent), ["Name", "Value"]);
});

test("no chart function writes innerHTML", () => {
  const doc = fakeDoc();
  K.stackedBars(doc, { bars: [{ label: "x", href: "#/x", values: { "claude-haiku-5": 5 } }], keys: slots, metric: "m" });
  K.hBars(doc, [{ label: "x", values: { "claude-haiku-5": 5 } }], slots);
  K.stripBySize(doc, { points: [{ size: "S", turns: 1 }], baselines: {}, metric: "turns" });
  K.legend(doc, slots);
  K.numbersTable(doc, [{ key: "a", label: "A" }], [{ a: "<b>x</b>" }]);
  assert.equal(doc.innerHtmlWrites.length, 0);
  const src = fs.readFileSync(new URL("../../portal/charts.js", import.meta.url), "utf8");
  assert.equal((src.match(/innerHTML *=/g) || []).length, 0);
  assert.equal((src.match(/\.style\./g) || []).length, 0, "colours are CSS classes, not inline values");
});

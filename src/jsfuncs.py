"""In-page JavaScript helpers.

Installed with `context.add_init_script` so they exist on every document, and
called from `src/dom.py`. They are deliberately generic (label -> nearby value,
table scraping, empty-state detection) because LinkedIn's admin analytics CSS
class names are build-hashed and change without notice; anchoring on visible
labels survives that, and every value is returned with the surrounding text as
evidence so a human can verify it against the UI.
"""

INSTALL_JS = r"""
(() => {
  if (window.__lia) return;

  const SEP = '\u0000';  /* sentinel marking where a matched label was removed */
  const norm = (s) => (s || '').replace(/[\u00a0\u202f\u2009]/g, ' ')
                               .replace(/\s+/g, ' ').trim();

  /* A number is NOT the metric value when it is part of a range descriptor
     ("Past 28 days") or a comparison ("vs previous 30 days", "12% increase"). */
  const SKIP_BEFORE = /(past|last|previous|prior|vs\.?|versus|compared(\s+to)?|over the|next|within)\s*$|(increase|decrease|change|growth)\s*(of)?\s*$|(step|page)\s+$/i;
  const SKIP_AFTER = /^\s*(days?|weeks?|months?|years?|hrs?|hours?)\b|^\s*%?\s*(increase|decrease|change|vs\b)/i;

  const lia = {
    norm,

    visible(el) {
      if (!el || !el.getBoundingClientRect) return false;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return false;
      const st = window.getComputedStyle(el);
      return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
    },

    /* In the layout tree at all? (survives carousels, clipped and scrolled
       containers, unlike a strict width/height check) */
    inLayout(el) {
      if (!el || !el.isConnected) return false;
      const st = window.getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden') return false;
      if (el.closest && el.closest('[aria-hidden="true"]')) return false;
      return !!(el.offsetParent || el.getClientRects().length ||
                (el.closest && el.closest('[class*="carousel"]')));
    },

    ownText(el) {
      let s = '';
      for (const n of el.childNodes) if (n.nodeType === 3) s += n.nodeValue;
      s = norm(s);
      if (!s && el.children.length === 0) s = norm(el.textContent);
      return s;
    },

    path(el) {
      const parts = [];
      let n = el;
      for (let i = 0; n && i < 4; i++, n = n.parentElement) {
        let p = n.tagName ? n.tagName.toLowerCase() : '';
        if (n.className && typeof n.className === 'string') {
          p += '.' + n.className.trim().split(/\s+/).slice(0, 2).join('.');
        }
        parts.unshift(p);
      }
      return parts.join(' > ');
    },

    /* Pick the numeric token that belongs to `label` inside `text`.

       LinkedIn's admin analytics renders the VALUE ABOVE THE LABEL and the
       period-over-period change BELOW it ("50,195 / Impressions / 0.9%"), while
       other surfaces put the value after the label. So: collect the nearest
       number on each side of the label and take whichever is closer, skipping
       bare percentages unless the metric itself is a rate (engagement rate,
       CTR) — a bare "%" next to a count is a change indicator, not the value. */
    pickNumber(text, label, allowPercent) {
      const lab = String(label);
      const li = text.toLowerCase().indexOf(lab.toLowerCase());
      if (li < 0) return null;
      const before = text.slice(0, li);
      const after = text.slice(li + lab.length);

      const clean = (s) => s
        .replace(/[▲▼↑↓]\s*[\d.,]+\s*%/g, ' ')
        .replace(/[+\-]\s?[\d.,]+\s*%/g, ' ')
        .replace(/[\d.,]+\s*%\s*(increase|decrease)/gi, ' ')
        .replace(/\b(increase|decrease)d?\s+by\s+[\d.,]+\s*%/gi, ' ');

      const NUM = /([0-9][0-9,.’']*)\s*(%|K|M|B|k|bn|mn)?/g;

      const scan = (segment, fromEnd) => {
        const seg = clean(segment);
        const hits = [];
        let m;
        NUM.lastIndex = 0;
        while ((m = NUM.exec(seg)) !== null) {
          const prevChar = m.index > 0 ? seg[m.index - 1] : ' ';
          if (/[\w.,%]/.test(prevChar)) continue;          /* mid-number match */
          const token = norm(m[1] + (m[2] || ''));
          const isPct = /%/.test(token);
          if (isPct && !allowPercent) continue;
          const numStart = m.index;
          const ctxBefore = seg.slice(Math.max(0, numStart - 16), numStart);
          const ctxAfter = seg.slice(numStart + m[0].length,
                                     numStart + m[0].length + 14);
          if (SKIP_BEFORE.test(ctxBefore) || SKIP_AFTER.test(ctxAfter)) continue;
          /* distance from the label: end-of-segment for `before`,
             start-of-segment for `after` */
          const distance = fromEnd ? seg.length - (numStart + m[0].length) : numStart;
          hits.push({ token: token, distance: distance, isPct: isPct,
                      context: norm(ctxBefore + token + ctxAfter) });
        }
        return hits;
      };

      const cands = scan(before, true).concat(scan(after, false));
      if (!cands.length) return null;
      /* prefer a plain count over a percentage, then proximity to the label */
      cands.sort((a, b) => (a.isPct - b.isPct) || (a.distance - b.distance));
      return { token: cands[0].token, context: cands[0].context };
    },

    /* Free-text value next to a label (durations, dates, "1h 23m", ...). */
    pickText(text, label) {
      const lab = String(label);
      const li = text.toLowerCase().indexOf(lab.toLowerCase());
      if (li < 0) return null;
      let after = norm(text.slice(li + lab.length).replace(/^[:\-–\s]+/, ''));
      if (!after) {
        const before = norm(text.slice(0, li));
        if (!before) return null;
        after = before.split(' ').slice(-6).join(' ');
      }
      return { token: after.slice(0, 80), context: norm(text).slice(0, 200) };
    },

    /* Find the value rendered next to one of `labels`. mode: 'number' | 'text' */
    findMetric(labels, mode, allowPercent) {
      mode = mode || 'number';
      allowPercent = !!allowPercent;
      const wants = labels.map((l) => String(l).toLowerCase());
      const els = document.querySelectorAll(
        'h1,h2,h3,h4,h5,h6,p,span,div,dt,dd,th,td,li,strong,b,button,a,figcaption'
      );
      const out = [];
      for (const el of els) {
        const own = this.ownText(el).toLowerCase().replace(/[:•]$/, '').trim();
        if (!own || own.length > 70) continue;
        let idx = -1;
        for (let i = 0; i < wants.length; i++) {
          const w = wants[i];
          if (own === w) { idx = i; break; }
          /* tolerate decorations only: "Impressions:", "Clicks (organic)",
             "Reactions ⓘ" — but never section headings such as
             "Page views by page", which would steal a table value. */
          if (own.startsWith(w)) {
            const rest = own.slice(w.length);
            if (rest.length <= 16 && /^[\s]*[:\-\u2013\u2022(\/|]/.test(rest)) { idx = i; break; }
            /* "New followers in the last 30 days" is still "New followers" */
            if (/^\s+(in|over|for|during)\s+(the\s+)?(last|past)\s+\d+\s+(day|days|week|weeks|month|months)$/i
                .test(rest)) { idx = i; break; }
          }
        }
        if (idx < 0) continue;
        /* Off-screen content (e.g. dashboard metric carousels) is still real
           data, so it is ranked lower rather than discarded; truly hidden
           nodes (display:none / visibility:hidden) are dropped. */
        if (!this.inLayout(el)) continue;
        const offscreen = !this.visible(el);
        /* a <th>/columnheader labels a table column, not a headline metric */
        const tag = el.tagName.toLowerCase();
        if (tag === 'th' || el.getAttribute('role') === 'columnheader') continue;
        if (el.closest && el.closest('thead')) continue;
        let node = el, found = null;
        for (let d = 0; d < 7 && node; d++, node = node.parentElement) {
          const text = norm(node.textContent);
          if (!text || text.length > 600) break;
          const cand = mode === 'text'
            ? this.pickText(text, labels[idx])
            : this.pickNumber(text, labels[idx], allowPercent);
          if (cand && cand.token) { found = { cand: cand, text: text, depth: d }; break; }
        }
        if (!found) continue;
        out.push({
          label: labels[idx],
          label_on_page: this.ownText(el),
          raw: found.cand.token,
          evidence: found.text.slice(0, 300),
          context: found.cand.context,
          depth: found.depth,
          path: this.path(el),
          offscreen: offscreen,
          score: (offscreen ? 10000000 : 0) + idx * 100000 + found.depth * 1000
                 + Math.min(found.text.length, 999)
        });
      }
      out.sort((a, b) => a.score - b.score);
      return out.length ? out[0] : null;
    },

    findAll(labels, mode, allowPercent) {
      const seen = {}, res = [];
      for (const l of labels) {
        const hit = this.findMetric([l], mode, allowPercent);
        if (hit && !seen[hit.raw + l]) { seen[hit.raw + l] = 1; res.push(hit); }
      }
      return res;
    },

    /* All tables / ARIA grids on the page, with header row, cells and row links. */
    tables() {
      const nodes = document.querySelectorAll('table,[role="table"],[role="grid"]');
      const out = [];
      nodes.forEach((t, i) => {
        if (!this.visible(t)) return;
        const headers = Array.from(
          t.querySelectorAll('thead th, [role="columnheader"]')
        ).map((h) => norm(h.textContent)).filter(Boolean);
        const rowEls = Array.from(t.querySelectorAll('tbody tr, [role="row"]'));
        const rows = [];
        for (const r of rowEls) {
          const cells = Array.from(
            r.querySelectorAll('td, th, [role="cell"], [role="gridcell"]')
          ).map((c) => norm(c.textContent));
          if (!cells.length || cells.every((c) => !c)) continue;
          if (headers.length && cells.join('|') === headers.join('|')) continue;
          const links = Array.from(r.querySelectorAll('a[href]')).map((a) => a.getAttribute('href'));
          rows.push({ cells: cells, links: links });
        }
        if (rows.length) {
          out.push({ index: i, headers: headers, rows: rows,
                     caption: norm((t.querySelector('caption') || {}).textContent || ''),
                     path: this.path(t) });
        }
      });
      return out;
    },

    /* Horizontal-bar style demographic breakdowns: "<label> <pct>%" list items. */
    breakdown(scopeText) {
      const roots = Array.from(document.querySelectorAll('section,div,ul,ol'));
      const cands = [];
      for (const root of roots) {
        const txt = norm(root.textContent);
        if (!txt || txt.length > 4000) continue;
        if (scopeText && txt.toLowerCase().indexOf(String(scopeText).toLowerCase()) < 0) continue;
        const items = Array.from(root.querySelectorAll('li,tr,[role="row"],[role="listitem"]'));
        const rows = [];
        for (const it of items) {
          const t = norm(it.textContent);
          if (!t || t.length > 120) continue;
          /* "Engineering  5,818 (25.4%)"  |  "Engineering  25.4%"  |  "Engineering 5,818" */
          let m = t.match(/^(.*?)[\s•|]*([0-9][0-9,.]*)\s*\(\s*([0-9][0-9.,]*)\s*%\s*\)$/);
          if (m && norm(m[1])) {
            rows.push({ label: norm(m[1]).replace(/[:\-–]+$/, ''),
                        value: m[2], percent: m[3] + '%' });
            continue;
          }
          m = t.match(/^(.*?)[\s•|]*([0-9][0-9,.]*)\s*(%?)$/);
          if (m && norm(m[1])) {
            rows.push({ label: norm(m[1]).replace(/[:\-–]+$/, ''), value: m[2] + m[3] });
          }
        }
        if (rows.length >= 2) cands.push({ rows: rows, size: txt.length, path: this.path(root) });
      }
      cands.sort((a, b) => a.size - b.size);
      return cands.length ? cands[0] : null;
    },

    /* Open the date-range control WITHOUT risking a click on unrelated content.
       A loose text match on "last 7 days" would hit the dashboard metric cards
       (whose labels contain that phrase) and navigate away from the page. */
    clickDateControl() {
      const RANGE = /^([A-Z][a-z]{2}\s+\d{1,2},?\s*\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4})\s*[-\u2013]\s*/;
      const PRESET = /^(past|last)\s+\d+\s+(day|days|week|weeks|month|months|year)s?$/i;
      const btns = Array.from(document.querySelectorAll('button,[role=button]'))
        .filter((b) => this.inLayout(b));
      const byAria = btns.find((b) => /^date range/i.test(b.getAttribute('aria-label') || ''));
      if (byAria) { byAria.click(); return 'aria'; }
      const byText = btns.find((b) => {
        const t = this.norm(b.textContent);
        return t.length < 60 && (RANGE.test(t) || PRESET.test(t));
      });
      if (byText) { byText.click(); return 'text'; }
      return '';
    },

    /* Click the deepest element whose own text matches `pattern` exactly.
       Used for artdeco dropdown options, which Playwright's role and text
       engines do not reliably match. */
    clickOwnText(pattern) {
      const re = new RegExp(pattern, 'i');
      const nodes = Array.from(document.querySelectorAll(
        'button,a,li,div,span,p,[role=option],[role=menuitem],[role=tab]'));
      const hits = nodes.filter((el) => re.test(this.ownText(el)) && this.inLayout(el));
      if (!hits.length) return false;
      /* deepest match = the actual clickable label rather than its wrapper */
      hits.sort((a, b) => b.querySelectorAll('*').length - a.querySelectorAll('*').length);
      const target = hits[hits.length - 1];
      const clickable = target.closest('button,a,[role=option],[role=menuitem],li') || target;
      clickable.click();
      return true;
    },

    /* Items listed under a heading, for lists LinkedIn renders without values
       (e.g. "Top keywords to find your Page"). Returns the heading text, the
       first following non-heading line group, and any sub-heading labels. */
    listAfterHeading(headingPattern, maxItems) {
      const re = new RegExp(headingPattern, 'i');
      maxItems = maxItems || 25;
      const heads = Array.from(document.querySelectorAll(
        'h1,h2,h3,h4,h5,h6,strong,b,span,div,p'));
      for (const h of heads) {
        const own = this.ownText(h);
        if (!own || own.length > 90 || !re.test(own)) continue;
        if (!this.visible(h)) continue;
        /* climb to the module that holds both the heading and its list */
        let node = h;
        for (let d = 0; d < 9 && node; d++, node = node.parentElement) {
          const items = Array.from(node.querySelectorAll('li,tr,[role=listitem],a,p,span,div'))
            .map((el) => this.ownText(el))
            .filter((s) => s && s.length < 90 && !re.test(s));
          const uniq = [];
          for (const s of items) {
            if (uniq.indexOf(s) < 0) uniq.push(s);
          }
          /* drop obvious chrome */
          const cleaned = uniq.filter((s) => !/^(show all|see more|export|about|help)/i.test(s));
          if (cleaned.length >= 2) {
            return { heading: own, items: cleaned.slice(0, maxItems),
                     depth: d, path: this.path(h) };
          }
        }
      }
      return null;
    },

    /* Analytics tab navigation discovered on the page. */
    navLinks() {
      return Array.from(document.querySelectorAll('a[href]'))
        .filter((a) => /\/admin\/(analytics|dashboard)/.test(a.getAttribute('href') || ''))
        .map((a) => ({ text: norm(a.textContent), href: a.href }))
        .filter((x) => x.text);
    },

    clickables(pattern) {
      const re = new RegExp(pattern, 'i');
      return Array.from(document.querySelectorAll('button,a[role="button"],[role="tab"],a[href]'))
        .filter((b) => this.visible(b) &&
                       re.test(norm(b.textContent) + ' ' + (b.getAttribute('aria-label') || '')))
        .map((b) => ({ text: norm(b.textContent), aria: b.getAttribute('aria-label') || '',
                       tag: b.tagName.toLowerCase(), path: this.path(b) }));
    },

    /* LinkedIn's own "no data" messaging — lets us report data_unavailable
       instead of blaming the automation. */
    emptyStates() {
      const pats = [
        /no data (available|to show|yet)/i, /not enough data/i, /no results/i,
        /nothing to (show|see) (here|yet)/i, /check back later/i,
        /you have no .{0,30} yet/i, /no activity/i, /data (is )?not available/i,
        /start posting/i, /no posts/i
      ];
      const out = [];
      document.querySelectorAll('p,span,div,h2,h3,h4,li').forEach((el) => {
        if (el.children.length) return;
        const t = norm(el.textContent);
        if (!t || t.length > 200) return;
        if (pats.some((p) => p.test(t)) && this.visible(el)) out.push(t);
      });
      return Array.from(new Set(out)).slice(0, 25);
    },

    /* Access / permission / auth walls. */
    accessWalls() {
      const pats = [
        /you don.?t have (access|permission)/i, /not authorized/i,
        /only (page )?admins/i, /request admin access/i,
        /page not found/i, /this page (doesn.?t|does not) exist/i,
        /sign in to linkedin/i, /join linkedin/i, /security verification/i,
        /let.?s do a quick security check/i
      ];
      const t = norm(document.body ? document.body.innerText : '');
      return pats.filter((p) => p.test(t)).map((p) => String(p));
    },

    dateRangeLabel() {
      /* An explicit range ("Oct 25, 2026 - Nov 23, 2026", "10/25/2026 - 11/23/2026")
         is authoritative; a bare preset ("Past 28 days") is second best. Strings
         carrying a "%" are change indicators, not range labels. */
      const EXPLICIT = /(\d{1,2}\/\d{1,2}\/\d{2,4}|[A-Z][a-z]{2}\s+\d{1,2},?\s*\d{4})\s*[-–]\s*(\d{1,2}\/\d{1,2}\/\d{2,4}|[A-Z][a-z]{2}\s+\d{1,2},?\s*\d{4})/;
      const PRESET = /^(past|last)\s+\d+\s+(day|days|week|weeks|month|months|year)/i;
      const explicit = [], preset = [];
      const nodes = Array.from(document.querySelectorAll('button,span,div,p,h2,h3'));
      for (const n of nodes) {
        if (n.children.length > 2) continue;
        const t = norm(n.textContent);
        if (!t || t.length > 90 || t.indexOf('%') >= 0) continue;
        if (!this.visible(n)) continue;
        const m = t.match(EXPLICIT);
        if (m) { explicit.push(norm(m[0])); continue; }
        if (PRESET.test(t)) preset.push(t);
      }
      /* also consider the control's accessible name, e.g.
         aria-label="Date range: Oct 25, 2026 - Nov 23, 2026" */
      document.querySelectorAll('[aria-label]').forEach((el) => {
        const a = norm(el.getAttribute('aria-label'));
        if (!a || a.length > 120) return;
        const m = a.match(EXPLICIT);
        if (m && this.visible(el)) explicit.unshift(norm(m[0]));
      });
      return Array.from(new Set(explicit.concat(preset))).slice(0, 8);
    },

    pageText() {
      return norm(document.body ? document.body.innerText : '');
    },

    rawText() {
      return document.body ? document.body.innerText : '';
    },

    /* Post URNs present anywhere on the page (table links, data attributes). */
    postUrns() {
      const found = new Set();
      const html = document.documentElement.innerHTML;
      const re = /urn:li:(?:activity|share|ugcPost):\d+/g;
      let m;
      while ((m = re.exec(html)) !== null) found.add(m[0]);
      return Array.from(found).slice(0, 200);
    }
  };

  window.__lia = lia;
})();
"""

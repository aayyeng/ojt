/* OJT Journal - front-end helpers */

// ---------------------------------------------------------------- utilities
function $(sel, root) { return (root || document).querySelector(sel); }
function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

function toast(message, type) {
  const el = $('#toast');
  if (!el) return alert(message);
  el.textContent = message;
  el.className = 'toast toast-' + (type || 'info');
  el.hidden = false;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.hidden = true; }, 4500);
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
  return data;
}

function setBusy(btn, busy, label) {
  if (!btn) return;
  if (busy) {
    btn.dataset.label = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span> ' + (label || 'Working...');
    btn.disabled = true;
  } else {
    btn.innerHTML = btn.dataset.label || btn.innerHTML;
    btn.disabled = false;
  }
}

function fmtMinutes(m) {
  m = Math.max(0, parseInt(m || 0, 10));
  const h = Math.floor(m / 60), r = m % 60;
  if (h && r) return h + 'h ' + r + 'm';
  if (h) return h + 'h';
  return r + 'm';
}

function minutesBetween(a, b) {
  if (!a || !b) return 0;
  const [ah, am] = a.split(':').map(Number);
  const [bh, bm] = b.split(':').map(Number);
  const d = (bh * 60 + bm) - (ah * 60 + am);
  return d > 0 ? d : 0;
}

function autoGrow(t) {
  t.style.height = 'auto';
  t.style.height = (t.scrollHeight + 2) + 'px';
}

function previewFiles(inputs, box) {
  if (!box) return;
  box.innerHTML = '';
  const list = Array.isArray(inputs) ? inputs : [inputs];
  list.forEach((input) => Array.from(input.files || []).forEach((f) => {
    const img = document.createElement('img');
    img.src = URL.createObjectURL(f);
    img.title = f.name;
    box.appendChild(img);
  }));
}

// --------------------------------------------------------- verifier rows
function getSavedVerifiers() {
  return Array.isArray(window.SAVED_VERIFIERS) ? window.SAVED_VERIFIERS : [];
}

function matchVerifiers(query) {
  const dir = getSavedVerifiers();
  const q = (query || '').trim().toLowerCase();
  if (!q) return dir.slice(0, 8).map((v) => ({ item: v, score: 1, exactKeyword: false }));
  const tokens = q.split(/\s+/).filter(Boolean);
  const scored = [];
  dir.forEach((v) => {
    const name = (v.name || '').toLowerCase();
    const title = (v.title || '').toLowerCase();
    const kwList = (v.keywords || '').split(/[,;]+/).map((s) => s.trim().toLowerCase()).filter(Boolean);
    const words = (name + ' ' + title + ' ' + kwList.join(' ')).split(/[\s,./-]+/).filter(Boolean);
    const hay = name + ' ' + title + ' ' + kwList.join(' ');
    if (!tokens.every((t) => hay.includes(t))) return;
    let score = 1;
    let exactKeyword = false;
    if (name === q) {
      score = 4;
      exactKeyword = true;
    } else if (kwList.includes(q) || words.includes(q)) {
      score = 3;
      exactKeyword = true;
    } else if (words.some((w) => w.startsWith(q)) || name.startsWith(q) || title.startsWith(q)) {
      score = 2;
    }
    scored.push({ item: v, score, exactKeyword });
  });
  scored.sort((a, b) => b.score - a.score || a.item.name.localeCompare(b.item.name));
  return scored;
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function initVerifierRows(options) {
  options = options || {};
  const list = $('#verifiers');
  if (!list) return;

  function applyVerifier(row, item, announce) {
    const nameIn = $('input[name=verifier_name]', row);
    const titleIn = $('input[name=verifier_title]', row);
    if (!nameIn || !item) return;
    nameIn.value = item.name || '';
    if (titleIn) titleIn.value = item.title || '';
    row.classList.remove('is-filled');
    void row.offsetWidth;
    row.classList.add('is-filled');
    nameIn.dispatchEvent(new Event('input', { bubbles: true }));
    if (announce) {
      toast('Filled: ' + item.name + (item.title ? ' (' + item.title + ')' : ''), 'success');
    }
  }

  function closeMenus(except) {
    $all('.verifier-menu', list).forEach((m) => {
      if (m !== except) m.remove();
    });
  }

  function wireRow(row) {
    const nameIn = $('input[name=verifier_name]', row);
    if (!nameIn || nameIn.dataset.wired) return;
    nameIn.dataset.wired = '1';
    let field = nameIn.closest('.verifier-field');
    if (!field) {
      field = document.createElement('div');
      field.className = 'verifier-field';
      nameIn.parentNode.insertBefore(field, nameIn);
      field.appendChild(nameIn);
    }

    let activeIdx = 0;
    let currentMatches = [];

    function renderMenu(showAll) {
      closeMenus();
      const q = nameIn.value.trim();
      if (!q && !showAll) return;
      currentMatches = matchVerifiers(q);
      if (!currentMatches.length) return;
      // Don't pop menu if already exact match on name and user isn't typing
      if (q && currentMatches.length === 1 && currentMatches[0].item.name.toLowerCase() === q.toLowerCase()) return;
      activeIdx = 0;
      const menu = document.createElement('div');
      menu.className = 'verifier-menu';
      currentMatches.slice(0, 6).forEach((m, idx) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'verifier-opt' + (idx === 0 ? ' is-active' : '');
        btn.innerHTML = '<strong>' + escapeHtml(m.item.name) + '</strong>' +
          (m.item.title ? '<small>' + escapeHtml(m.item.title) + '</small>' : '<small class="muted">No position</small>');
        btn.addEventListener('mousedown', (e) => {
          e.preventDefault();
          applyVerifier(row, m.item, false);
          menu.remove();
        });
        menu.appendChild(btn);
      });
      field.appendChild(menu);
    }

    function setActive(idx) {
      const menu = $('.verifier-menu', field);
      if (!menu) return;
      const opts = $all('.verifier-opt', menu);
      if (!opts.length) return;
      activeIdx = (idx + opts.length) % opts.length;
      opts.forEach((o, i) => o.classList.toggle('is-active', i === activeIdx));
    }

    nameIn.addEventListener('focus', () => renderMenu(true));
    nameIn.addEventListener('input', () => renderMenu(false));
    nameIn.addEventListener('keydown', (e) => {
      const menu = $('.verifier-menu', field);
      if (!menu || !currentMatches.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive(activeIdx + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive(activeIdx - 1);
      } else if (e.key === 'Escape') {
        menu.remove();
      } else if (e.key === 'Enter') {
        if (nameIn.value.trim()) {
          e.preventDefault();
          applyVerifier(row, currentMatches[activeIdx].item, false);
          menu.remove();
        }
      } else if (e.key === 'Tab' && nameIn.value.trim()) {
        const top = currentMatches[activeIdx];
        if (top && top.item.name.toLowerCase() !== nameIn.value.trim().toLowerCase()) {
          applyVerifier(row, top.item, false);
          menu.remove();
        }
      }
    });

    nameIn.addEventListener('blur', () => {
      setTimeout(() => {
        const menu = $('.verifier-menu', field);
        if (menu) menu.remove();
        const q = nameIn.value.trim();
        if (q.length < 2) return;
        const matches = matchVerifiers(q);
        if (!matches.length) return;
        const top = matches[0];
        if (top.item.name.toLowerCase() === q.toLowerCase()) {
          const titleIn = $('input[name=verifier_title]', row);
          if (titleIn && !titleIn.value.trim() && top.item.title) {
            titleIn.value = top.item.title;
          }
          return;
        }
        // Auto-convert typed word/keyword when it matches unambiguously (exact keyword or single prefix match)
        const exactHits = matches.filter((m) => m.exactKeyword);
        if (exactHits.length === 1) {
          applyVerifier(row, exactHits[0].item, true);
        } else if (matches.length === 1 && top.score >= 2) {
          applyVerifier(row, top.item, true);
        }
      }, 120);
    });
  }

  function addVerifierRow(prefill) {
    prefill = prefill || {};
    const row = document.createElement('div');
    row.className = 'verifier-row';
    row.innerHTML = '<div class="verifier-field">' +
      '<input name="verifier_name" placeholder="Type name or keyword (e.g. luis, it)" autocomplete="off">' +
      '</div>' +
      '<input name="verifier_title" placeholder="Position (optional)">' +
      '<button type="button" class="icon-btn" data-remove-row title="Remove">✕</button>';
    $('input[name=verifier_name]', row).value = prefill.name || '';
    $('input[name=verifier_title]', row).value = prefill.title || '';
    list.appendChild(row);
    wireRow(row);
    return row;
  }

  $all('.verifier-row', list).forEach(wireRow);
  if (options.ensureOne && !$all('.verifier-row', list).length) {
    addVerifierRow();
  }

  $all('[data-add-verifier]').forEach((btn) => btn.addEventListener('click', () => {
    const row = addVerifierRow();
    $('input[name=verifier_name]', row).focus();
  }));

  list.addEventListener('click', (e) => {
    if (e.target.matches('[data-remove-row]')) {
      e.target.closest('.verifier-row').remove();
      if (options.ensureOne && !$all('.verifier-row', list).length) addVerifierRow();
    }
  });

  const chips = $('#verifier-chips');
  if (chips) {
    chips.addEventListener('click', (e) => {
      const chip = e.target.closest('[data-pick-verifier]');
      if (!chip) return;
      const pick = { name: chip.dataset.pickVerifier, title: chip.dataset.pickTitle || '' };
      const rows = $all('.verifier-row', list);
      const existing = rows.find((r) => $('input[name=verifier_name]', r).value.trim().toLowerCase() === pick.name.toLowerCase());
      if (existing) {
        applyVerifier(existing, pick, false);
        return;
      }
      const empty = rows.find((r) => !$('input[name=verifier_name]', r).value.trim() && !$('input[name=verifier_title]', r).value.trim());
      const target = empty || addVerifierRow();
      applyVerifier(target, pick, false);
    });
  }
}

// ------------------------------------------------------------- entry page
let activityKey = 0;

function initEntryPage() {
  const form = $('#entry-form');
  const list = $('#activities');
  const tpl = $('#activity-template');
  let dirty = false;

  initVerifierRows({ ensureOne: true });

  function renumber() {
    $all('.activity', list).forEach((card, i) => { $('.num', card).textContent = i + 1; });
    updateTotal();
  }

  function cardMinutes(card) {
    const s = $('[data-f=start]', card).value, e = $('[data-f=end]', card).value;
    const between = minutesBetween(s, e);
    return between || parseInt($('[data-f=minutes]', card).value || 0, 10);
  }

  function updateCard(card) {
    const between = minutesBetween($('[data-f=start]', card).value, $('[data-f=end]', card).value);
    const minInput = $('[data-f=minutes]', card);
    if (between) { minInput.value = between; minInput.readOnly = true; }
    else { minInput.readOnly = false; }
    $('.duration', card).textContent = fmtMinutes(cardMinutes(card));
    updateTotal();
  }

  function updateTotal() {
    const total = $all('.activity', list).reduce((sum, c) => sum + cardMinutes(c), 0);
    $('#total-today').textContent = fmtMinutes(total);
  }

  function addPhoto(grid, p) {
    const fig = document.createElement('figure');
    fig.className = 'photo';
    fig.innerHTML = '<img alt="">' +
      '<input class="cap" placeholder="Caption (optional)">' +
      '<label class="check"><input type="checkbox"> Remove</label>';
    $('img', fig).src = p.url;
    const cap = $('.cap', fig);
    cap.name = 'pcap_' + p.id;
    cap.value = p.caption || '';
    $('input[type=checkbox]', fig).name = 'pdel_' + p.id;
    grid.appendChild(fig);
  }

  function addActivity(data) {
    data = data || {};
    const node = tpl.content.firstElementChild.cloneNode(true);
    const key = 'k' + (activityKey++);
    node.dataset.key = key;
    if (data.id) node.dataset.id = data.id;
    $('[data-f=start]', node).value = data.start || '';
    $('[data-f=end]', node).value = data.end || '';
    $('[data-f=minutes]', node).value = data.minutes || '';
    $('[data-f=raw]', node).value = data.raw || '';
    $('[data-f=text]', node).value = data.text || '';
    $('[data-f=caption]', node).value = data.caption || '';
    const fileInputs = $all('[data-photo-input]', node);
    fileInputs.forEach((input) => {
      input.name = 'photos_' + key;
      input.addEventListener('change', () => previewFiles(fileInputs, $('[data-preview]', node)));
    });
    const grid = $('[data-existing]', node);
    (data.photos || []).forEach((p) => addPhoto(grid, p));
    list.appendChild(node);
    $all('textarea', node).forEach(autoGrow);
    updateCard(node);
    renumber();
    return node;
  }

  list.addEventListener('input', (e) => {
    dirty = true;
    const card = e.target.closest('.activity');
    if (!card) return;
    if (e.target.matches('textarea')) autoGrow(e.target);
    if (e.target.matches('[data-f=start],[data-f=end],[data-f=minutes]')) updateCard(card);
  });

  list.addEventListener('click', async (e) => {
    const card = e.target.closest('.activity');
    if (!card) return;
    if (e.target.closest('[data-remove-activity]')) {
      const hasContent = $('[data-f=raw]', card).value || $('[data-f=text]', card).value ||
        $all('.photo', card).length;
      if (hasContent && !confirm('Remove this activity? Its photos will also be removed when you save.')) return;
      card.remove();
      dirty = true;
      renumber();
      if (!$all('.activity', list).length) addActivity();
    }
    const polishBtn = e.target.closest('[data-polish]');
    if (polishBtn) {
      const raw = $('[data-f=raw]', card).value.trim() || $('[data-f=text]', card).value.trim();
      if (!raw) { toast('Write what you did first.', 'error'); return; }
      setBusy(polishBtn, true, 'Polishing...');
      try {
        const res = await postJSON('/api/polish', { notes: [raw] });
        applyPolish(card, res.items[0]);
        toast('Done! Check the text before saving.', 'success');
      } catch (err) { toast(err.message, 'error'); }
      setBusy(polishBtn, false);
    }
  });

  function applyPolish(card, item) {
    if (!item) return;
    const t = $('[data-f=text]', card);
    t.value = item.text || t.value;
    autoGrow(t);
    if (item.caption) $('[data-f=caption]', card).value = item.caption;
    dirty = true;
  }

  $('#polish-all').addEventListener('click', async (e) => {
    const cards = $all('.activity', list).filter((c) => $('[data-f=raw]', c).value.trim());
    if (!cards.length) { toast('Write your activities first.', 'error'); return; }
    const btn = e.currentTarget;
    setBusy(btn, true, 'Polishing...');
    try {
      const res = await postJSON('/api/polish', { notes: cards.map((c) => $('[data-f=raw]', c).value.trim()) });
      cards.forEach((c, i) => applyPolish(c, res.items[i]));
      toast('All activities polished. Review them, then save.', 'success');
    } catch (err) { toast(err.message, 'error'); }
    setBusy(btn, false);
  });

  ['#add-activity', '#add-activity-2'].forEach((id) => $(id).addEventListener('click', () => {
    const node = addActivity();
    $('[data-f=raw]', node).focus();
  }));

  $('input[name=ncis_files]').addEventListener('change', (e) =>
    previewFiles(e.target, $('#' + e.target.dataset.preview)));

  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('submit', (e) => {
    const items = $all('.activity', list).map((c) => ({
      id: c.dataset.id ? parseInt(c.dataset.id, 10) : null,
      key: c.dataset.key,
      start: $('[data-f=start]', c).value,
      end: $('[data-f=end]', c).value,
      minutes: parseInt($('[data-f=minutes]', c).value || 0, 10),
      raw: $('[data-f=raw]', c).value.trim(),
      text: $('[data-f=text]', c).value.trim(),
      caption: $('[data-f=caption]', c).value.trim(),
    }));
    const missing = items.filter((i) => (i.raw || i.text) && !i.start && !i.end && !i.minutes);
    if (missing.length && !confirm(missing.length + ' activit' + (missing.length > 1 ? 'ies have' : 'y has') +
        ' no time yet, so it will count as 0 hours. Save anyway?')) {
      e.preventDefault();
      return;
    }
    $('#activities_json').value = JSON.stringify(items);
    const submitter = e.submitter;
    $('#after').value = submitter && submitter.dataset.after ? submitter.dataset.after : '';
    dirty = false;
  });
  window.addEventListener('beforeunload', (e) => {
    if (dirty) { e.preventDefault(); e.returnValue = ''; }
  });

  (window.ENTRY_ACTIVITIES || []).forEach((a) => addActivity(a));
  if (!$all('.activity', list).length) addActivity();
  if ((window.ENTRY_LOOSE_PHOTOS || []).length) {
    const first = $('.activity', list);
    window.ENTRY_LOOSE_PHOTOS.forEach((p) => addPhoto($('[data-existing]', first), p));
  }
  dirty = false;
}

// -------------------------------------------------------------- week page
function initWeekPage() {
  const list = $('#training-list');
  const tpl = $('#training-template');
  const form = $('#week-form');
  const locked = !!window.WEEK_LOCKED;
  const badges = $all('[data-autosave-badge]');

  let dirty = false;
  let saveTimer = null;
  let inFlight = false;
  let queued = false;

  const field = (name) => form.querySelector('[name=' + name + ']');
  const splitLines = (v) => String(v || '').split('\n').map((x) => x.trim()).filter(Boolean);

  function setStatus(state, text) {
    badges.forEach((el) => {
      el.textContent = text;
      el.className = 'autosave-pill' + (state ? ' is-' + state : '');
    });
  }

  function collectTraining() {
    return $all('.training-card', list).map((c) => ({
      category: $('[data-t=category]', c).value.trim(),
      how: splitLines($('[data-t=how]', c).value),
      trainers: $all('[data-t=trainer-item]', c).map((el) => el.value.trim()).filter(Boolean),
      timeline: $all('[data-t=timeline-item]', c).map((el) => el.value.trim()).filter(Boolean),
      outputs: splitLines($('[data-t=outputs]', c).value),
    }));
  }

  function collectWeekPayload() {
    return {
      problems_raw: field('problems_raw').value,
      solutions_raw: field('solutions_raw').value,
      goals_raw: field('goals_raw').value,
      problems: field('problems').value,
      solutions: field('solutions').value,
      goals: field('goals').value,
      duties: field('duties').value,
      new_trainings: field('new_trainings').value,
      proposed: field('proposed').value,
      accomplishments: field('accomplishments').value,
      learning_activities: field('learning_activities').value,
      learning_outcomes: field('learning_outcomes').value,
      training: collectTraining(),
    };
  }

  async function saveNow() {
    if (locked) return;
    clearTimeout(saveTimer);
    saveTimer = null;
    if (inFlight) {
      queued = true;
      return;
    }
    inFlight = true;
    dirty = false;
    setStatus('saving', 'Saving...');
    try {
      const res = await postJSON('/api/week/' + window.WEEK_NO + '/autosave', collectWeekPayload());
      setStatus('saved', 'Saved ✓ ' + (res.saved_at || ''));
    } catch (err) {
      dirty = true;
      setStatus('error', 'Save failed — click Save');
    } finally {
      inFlight = false;
      if (queued) {
        queued = false;
        saveNow();
      }
    }
  }

  function scheduleAutosave(immediate) {
    if (locked) return;
    dirty = true;
    clearTimeout(saveTimer);
    if (immediate) {
      saveNow();
      return;
    }
    setStatus('dirty', 'Unsaved changes...');
    saveTimer = setTimeout(saveNow, 1000);
  }

  function flushBeacon() {
    if (locked || !dirty) return;
    clearTimeout(saveTimer);
    saveTimer = null;
    try {
      const blob = new Blob([JSON.stringify(collectWeekPayload())], { type: 'application/json' });
      if (navigator.sendBeacon && navigator.sendBeacon('/api/week/' + window.WEEK_NO + '/autosave', blob)) {
        dirty = false;
      }
    } catch (e) { /* ignore */ }
  }

  function addTrainerRow(card, value, focus) {
    const box = $('[data-trainer-list]', card);
    if (!box) return;
    if (value) {
      const exists = $all('[data-t=trainer-item]', box).some(
        (el) => el.value.trim().toLowerCase() === value.trim().toLowerCase()
      );
      if (exists) return;
    }
    const row = document.createElement('div');
    row.className = 'timeline-row';
    row.innerHTML = '<input data-t="trainer-item" placeholder="Trainer full name">' +
      '<button type="button" class="icon-btn" data-remove-trainer title="Remove trainer">✕</button>';
    const inp = $('input', row);
    inp.value = value || '';
    box.appendChild(row);
    if (focus) inp.focus();
  }

  function addTimelineRow(card, value, focus) {
    const box = $('[data-timeline-list]', card);
    if (!box) return;
    const row = document.createElement('div');
    row.className = 'timeline-row';
    row.innerHTML = '<input data-t="timeline-item" placeholder="e.g. Nov 24, 2026 or 2 hours">' +
      '<button type="button" class="icon-btn" data-remove-timeline title="Remove timeline">✕</button>';
    const inp = $('input', row);
    inp.value = value || '';
    box.appendChild(row);
    if (focus) inp.focus();
  }

  function addTraining(t) {
    t = t || {};
    const node = tpl.content.firstElementChild.cloneNode(true);
    $('[data-t=category]', node).value = t.category || '';
    $('[data-t=how]', node).value = (t.how || []).join('\n');
    const trainers = Array.isArray(t.trainers) ? t.trainers : splitLines(t.trainers);
    trainers.forEach((tr) => addTrainerRow(node, tr, false));
    const timelines = Array.isArray(t.timeline) ? t.timeline : splitLines(t.timeline);
    timelines.forEach((tl) => addTimelineRow(node, tl, false));
    $('[data-t=outputs]', node).value = (t.outputs || []).join('\n');
    list.appendChild(node);
  }

  function setTraining(items) {
    list.innerHTML = '';
    (items || []).forEach(addTraining);
  }

  list.addEventListener('click', (e) => {
    if (e.target.closest('[data-remove-training]')) {
      e.target.closest('.training-card').remove();
      scheduleAutosave(true);
      return;
    }
    if (e.target.closest('[data-remove-trainer]')) {
      e.target.closest('.timeline-row').remove();
      scheduleAutosave(true);
      return;
    }
    if (e.target.closest('[data-remove-timeline]')) {
      e.target.closest('.timeline-row').remove();
      scheduleAutosave(true);
    }
  });
  list.addEventListener('change', (e) => {
    const tpick = e.target.closest('[data-trainer-pick]');
    if (tpick && tpick.value) {
      const card = tpick.closest('.training-card');
      const val = tpick.value;
      tpick.value = '';
      if (val === '__custom__') {
        addTrainerRow(card, '', true);
      } else {
        addTrainerRow(card, val, false);
        scheduleAutosave(true);
      }
      return;
    }
    const pick = e.target.closest('[data-timeline-pick]');
    if (!pick || !pick.value) return;
    const card = pick.closest('.training-card');
    const val = pick.value;
    pick.value = '';
    if (val === '__custom__') {
      addTimelineRow(card, '', true);
    } else {
      addTimelineRow(card, val, false);
      scheduleAutosave(true);
    }
  });
  $('#add-training').addEventListener('click', () => {
    addTraining({});
    const last = list.lastElementChild;
    if (last) $('[data-t=category]', last).focus();
  });

  form.addEventListener('input', (e) => {
    if (e.target.matches('input, textarea')) scheduleAutosave(false);
  });
  form.addEventListener('change', (e) => {
    if (e.target.matches('input, textarea')) scheduleAutosave(false);
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushBeacon();
  });
  window.addEventListener('pagehide', flushBeacon);
  window.addEventListener('beforeunload', (e) => {
    flushBeacon();
    if (dirty || inFlight) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  $('#polish-reflection').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const body = {
      problems: field('problems_raw').value, solutions: field('solutions_raw').value,
      goals: field('goals_raw').value,
    };
    if (!body.problems.trim() && !body.solutions.trim() && !body.goals.trim()) {
      toast('Write your notes first.', 'error'); return;
    }
    setBusy(btn, true, 'Polishing...');
    try {
      const res = await postJSON('/api/reflection', body);
      ['problems', 'solutions', 'goals'].forEach((k) => {
        if (res[k] && res[k].length) field(k).value = res[k].join('\n');
      });
      await saveNow();
      toast('Notes polished and auto-saved!', 'success');
    } catch (err) { toast(err.message, 'error'); }
    setBusy(btn, false);
  });

  const gen = $('#generate-week');
  if (gen) gen.addEventListener('click', async () => {
    const hasContent = ['duties', 'new_trainings', 'learning_outcomes'].some((k) => field(k).value.trim());
    if (hasContent && !confirm('Replace the current report content with a new AI version?')) return;
    setBusy(gen, true, 'Generating...');
    try {
      const res = await postJSON('/api/week/' + window.WEEK_NO + '/generate');
      ['duties', 'new_trainings', 'proposed', 'learning_activities', 'learning_outcomes'].forEach((k) => {
        field(k).value = (res[k] || []).join('\n');
      });
      field('accomplishments').value = (res.accomplishments || []).join('\n\n');
      setTraining(res.training || []);
      await saveNow();
      toast('Generated and auto-saved! Review before downloading.', 'success');
    } catch (err) { toast(err.message, 'error'); }
    setBusy(gen, false);
  });

  form.addEventListener('submit', () => {
    clearTimeout(saveTimer);
    dirty = false;
    $('#training_json').value = JSON.stringify(collectTraining());
  });

  setTraining(window.WEEK_TRAINING || []);
}

// ---------------------------------------------------------- settings page
function initSettingsPage() {
  initVerifierRows({ ensureOne: false });
  const svList = $('#saved-verifiers');
  if (svList) {
    $all('[data-add-saved-verifier]').forEach((btn) => btn.addEventListener('click', () => {
      const row = document.createElement('div');
      row.className = 'verifier-row saved-verifier-row';
      row.innerHTML = '<input type="hidden" name="sv_orig_name" value="">' +
        '<input name="sv_name" placeholder="Full name">' +
        '<input name="sv_title" placeholder="Position (optional)">' +
        '<input name="sv_keywords" placeholder="Keywords (e.g. luis, accounting)">' +
        '<button type="button" class="icon-btn" data-remove-row title="Remove">✕</button>';
      svList.appendChild(row);
      $('input[name=sv_name]', row).focus();
    }));
    svList.addEventListener('click', (e) => {
      if (e.target.matches('[data-remove-row]')) e.target.closest('.verifier-row').remove();
    });
  }
  const btn = $('#test-ai');
  if (btn) btn.addEventListener('click', async () => {
    setBusy(btn, true, 'Testing...');
    try {
      await postJSON('/api/test-ai');
      toast('AI is working! ✅', 'success');
    } catch (err) { toast(err.message, 'error'); }
    setBusy(btn, false);
  });
}

// ------------------------------------------------ portable database import
function initRestoreForms() {
  const CHUNK_SIZE = 2 * 1024 * 1024; // 2 MB chunks (safe under Vercel's 4.5 MB limit)
  $all('form[data-restore-form]').forEach((form) => {
    form.addEventListener('submit', async (e) => {
      const input = $('input[type=file]', form);
      const file = input && input.files && input.files[0];
      if (!file) return;
      const msg = form.dataset.confirm;
      if (msg && !confirm(msg)) {
        e.preventDefault();
        return;
      }
      // Files <= 3 MB can use the standard fast form POST directly
      if (file.size <= 3 * 1024 * 1024) return;

      e.preventDefault();
      const btn = $('button[type=submit]', form);
      const total = Math.ceil(file.size / CHUNK_SIZE);
      const uploadId = 'up_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
      setBusy(btn, true, 'Uploading 0%...');
      try {
        let lastRes = null;
        for (let i = 0; i < total; i++) {
          const slice = file.slice(i * CHUNK_SIZE, Math.min(file.size, (i + 1) * CHUNK_SIZE));
          const fd = new FormData();
          fd.append('upload_id', uploadId);
          fd.append('filename', file.name);
          fd.append('index', String(i));
          fd.append('total', String(total));
          fd.append('chunk', slice, file.name);
          const pct = Math.round(((i + 1) / total) * 100);
          btn.innerHTML = '<span class="spinner"></span> ' + (i + 1 < total ? 'Uploading ' + pct + '%...' : 'Restoring...');
          const res = await fetch('/api/restore-chunk', { method: 'POST', body: fd });
          let data = {};
          try { data = await res.json(); } catch (err) { /* ignore */ }
          if (!res.ok) throw new Error(data.error || 'Import failed. Please try again.');
          lastRes = data;
        }
        if (lastRes && lastRes.redirect) {
          location.href = lastRes.redirect;
        } else {
          location.reload();
        }
      } catch (err) {
        toast(err.message, 'error');
        setBusy(btn, false);
      }
    });
  });
}

document.addEventListener('DOMContentLoaded', initRestoreForms);

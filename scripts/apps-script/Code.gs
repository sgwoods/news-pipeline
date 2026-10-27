/**
 * AI Briefing: email subscriptions, sent from the briefing account (briefing@example.com).
 *
 * Setup (2026-10-15): a STANDALONE script owned by the briefing account, deployed as a Web app
 * ("Execute as: Me", "Who has access: Anyone"), using the subscriber Sheet shared with it (SHEET_ID).
 *   public   subscribe (landing page form) -> confirmation email -> confirm link -> active
 *            unsubscribe link in every email -> unsubscribed (one click, no login)
 *            rate link (stars in the email and on the site) -> a confirm page -> POST records 1-5 + an
 *            optional note. The click only opens the page: link scanners that open every URL in an
 *            email cannot cast ratings. Email stars carry the subscriber's token; site stars are anonymous.
 *            deep-dive queue page (Steven only: signed owner link from his evening note): pick what airs
 *            next, move up/down, dismiss, suggest a topic; the pipeline applies the clicks at its next run
 *   private  (needs the SECRET script property; used by the pipeline and the dashboard)
 *            list · add (always sends a confirmation) · remove · send (subscribers or OWNER_EMAIL only)
 *            ratings (read-only export, no addresses) · setqueue / ddactions (the deep-dive queue page)
 *            takes (Steven's takes from the site or review page, owner token t) · takes_pull (the pipeline reads them)
 *            review (GET: the held edition with a box per section, owner token t) · setreview (the pipeline uploads it)
 *            savedoc (the edition and deep dive as Google Docs in the Briefings folder in Drive)
 *
 * Script properties (Project Settings -> Script properties):
 *   SHEET_ID     the shared subscriber Sheet's ID (from its URL, between /d/ and /edit)
 *   SECRET       a long random string; the same value is the pipeline's EMAIL_SCRIPT_KEY
 *   OWNER_EMAIL  comma-separated addresses allowed one-off sends (tests, Steven's private note)
 *   REPLY_TO     where replies go (briefing+feedback@example.com)
 *   FROM_NAME    AI Briefing
 *   SITE_URL     https://sgwoods.github.io/ai-briefing/
 *   DRIVE_FOLDER_ID  optional: the Drive folder for the edition docs (else the folder named Briefings)
 *
 * Consumer Gmail allows about 100 recipients a day through Apps Script; `send` reports the remaining quota.
 */

var SHEET = 'subscribers';
var HEAD = ['email', 'status', 'token', 'created', 'confirmed', 'updated', 'source', 'consent'];
var RSHEET = 'ratings';
var RHEAD = ['day', 'who', 'email', 'score', 'note', 'at', 'src'];
var QSHEET = 'dd_queue', QHEAD = ['id', 'topic', 'status', 'why', 'take'];   // take: Steven's own words on it
var ASHEET = 'dd_actions', AHEAD = ['at', 'op', 'id', 'topic', 'angle'];
var TSHEET = 'takes', THEAD = ['at', 'day', 'slot', 'text', 'done'];   // Steven's takes from the site page
var VSHEET = 'review', VHEAD = ['day', 'part', 'html'];                 // the held edition as a private review page
var CONSENT = 'Asked to receive the daily AI Briefing by email and confirmed by clicking the link sent to this address.';

function props_() { return PropertiesService.getScriptProperties(); }
function site_() { return props_().getProperty('SITE_URL') || 'https://sgwoods.github.io/ai-briefing/'; }
function fromName_() { return props_().getProperty('FROM_NAME') || 'AI Briefing'; }
// Security (2026-10-15): replies go to REPLY_TO (the briefing's own address) when set, and a "send" may only
// reach active subscribers or OWNER_EMAIL, so a leaked key cannot turn this account into a mail relay.
function replyTo_() { return props_().getProperty('REPLY_TO') || ''; }
// OWNER_EMAIL: comma-separated addresses that may get one-off sends (tests, Steven's private note)
function owners_() {
  return String(props_().getProperty('OWNER_EMAIL') || Session.getEffectiveUser().getEmail() || '')
    .toLowerCase().split(',').map(function (s) { return s.trim(); }).filter(String);
}
function mailOpts_(o) { var r = replyTo_(); if (r) o.replyTo = r; return o; }
function selfUrl_() { return ScriptApp.getService().getUrl(); }

function sheet_() {
  // SHEET_ID: a standalone script (owned by the briefing account) using a Sheet shared with it.
  // Without it, the script is bound to its own Sheet (the original setup).
  var id = props_().getProperty('SHEET_ID');
  var ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET) || ss.insertSheet(SHEET);
  if (sh.getLastRow() === 0) sh.appendRow(HEAD);
  return sh;
}

function rsheet_() {
  var id = props_().getProperty('SHEET_ID');
  var ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(RSHEET) || ss.insertSheet(RSHEET);
  if (sh.getLastRow() === 0) sh.appendRow(RHEAD);
  return sh;
}

function rrows_() {
  var sh = rsheet_(), v = sh.getDataRange().getValues(), out = [];
  for (var i = 1; i < v.length; i++) {
    var r = {}; RHEAD.forEach(function (h, j) { r[h] = v[i][j]; }); r._row = i + 1; out.push(r);
  }
  return out;
}

// Sheets turns "2026-10-16" into a Date; always hand back plain text.
function dayStr_(v) {
  return (v instanceof Date) ? Utilities.formatDate(v, Session.getScriptTimeZone(), 'yyyy-MM-dd') : String(v || '');
}
function isoStr_(v) { return (v instanceof Date) ? v.toISOString() : String(v || ''); }

// Steven's links carry signed owner tokens: one scope each (r = rating, q = queue page), a date, and an expiry
// (security review 2026-10-18, H2). Rotating SECRET invalidates every owner token at once.
var OWNER_DAYS = { r: 35, q: 8, t: 2 };      // t = takes on the site page (2 days)
function ymd_(d) { return Utilities.formatDate(d, 'UTC', 'yyyyMMdd'); }
function ownerSig_(email, scope, day) {
  var sig = Utilities.computeHmacSha256Signature(String(email).toLowerCase() + '|' + scope + '|' + day,
                                                  props_().getProperty('SECRET') || '');
  return Utilities.base64EncodeWebSafe(sig).replace(/=+$/, '').slice(0, 32);
}
function ownerToken_(email, scope) {
  scope = scope || 'r';
  var day = ymd_(new Date());
  return 'o' + scope + day + ownerSig_(email, scope, day);
}
function ownerOf_(t, scope) {                         // the owner address a token was issued to, or null
  var m = /^o([rqt])(\d{8})([A-Za-z0-9_-]{32})$/.exec(String(t || ''));
  if (!m || (scope && m[1] !== scope)) return null;
  var issued = new Date(Date.UTC(+m[2].slice(0, 4), +m[2].slice(4, 6) - 1, +m[2].slice(6, 8)));
  var age = (Date.now() - issued.getTime()) / 86400000;
  if (age < -1 || age > OWNER_DAYS[m[1]]) return null;
  return owners_().filter(function (o) { return ownerSig_(o, m[1], m[2]) === m[3]; })[0] || null;
}
function rater_(t) {                                  // token -> {email} (subscriber or owner) or null
  if (!t) return null;
  if (String(t).charAt(0) === 'o') {
    var hit = ownerOf_(t, 'r');
    return hit ? { email: hit } : null;
  }
  return find_('token', t) || null;
}

function validDay_(d) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(d || ''))) return false;
  var age = (Date.now() - new Date(d + 'T12:00:00Z').getTime()) / 86400000;
  return age > -2 && age < 31;                       // editions from the last month only
}

// One rating per subscriber per day (a second click replaces the first); site stars are anonymous and capped.
function saveRating_(day, score, note, sub) {
  var who = sub ? (owners_().indexOf(String(sub.email).toLowerCase()) >= 0 ? 'steven' : 'reader') : 'web';
  var row = { day: day, who: who, email: sub ? String(sub.email).toLowerCase() : '', score: score,
              note: String(note || '').replace(/[\u0000-\u001f]+/g, ' ').slice(0, 600), at: now_(), src: sub ? 'email' : 'site' };
  var sh = rsheet_();
  var prev = sub ? rrows_().filter(function (r) { return dayStr_(r.day) === day && String(r.email) === row.email; })[0] : null;
  var vals = [RHEAD.map(function (h) { return row[h]; })];
  var at = prev ? prev._row : sh.getLastRow() + 1;
  sh.getRange(at, 1, 1, RHEAD.length).setNumberFormat('@').setValues(vals);   // text: no date conversion
  return row;
}

function tab_(name, head) {
  var id = props_().getProperty('SHEET_ID');
  var ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) sh.appendRow(head);
  return sh;
}


function tabRows_(name, head) {
  var v = tab_(name, head).getDataRange().getValues(), out = [];
  for (var i = 1; i < v.length; i++) { var r = {}; head.forEach(function (h, j) { r[h] = String(v[i][j]); }); out.push(r); }
  return out;
}

function writeQueue_(rows) {                         // the snapshot the queue page shows (pipeline order)
  var sh = tab_(QSHEET, QHEAD);
  if (sh.getLastRow() > 1) sh.getRange(2, 1, sh.getLastRow() - 1, QHEAD.length).clearContent();
  if (rows.length) sh.getRange(2, 1, rows.length, QHEAD.length).setNumberFormat('@')
    .setValues(rows.map(function (r) { return QHEAD.map(function (h) { return String(r[h] || '').slice(0, h === 'take' ? 800 : 300); }); }));
}

function isOwnerToken_(t) { return !!ownerOf_(t, 'q'); }

// Sheets runs a cell that starts with = + - @ as a formula: text typed on the page is stored as plain text.
function safeCell_(v) { v = String(v == null ? '' : v); return /^[=+\-@\t\r]/.test(v) ? "'" + v : v; }

function clean_(s, n) { return String(s || '').replace(/[\u0000-\u001f]+/g, ' ').trim().slice(0, n); }

// One action from the page: logged for the pipeline, and applied to the snapshot so the page shows it now.
function queueAction_(op, id, topic, angle) {
  tab_(ASHEET, AHEAD).appendRow([now_(), op, clean_(id, 20), clean_(topic, 200), clean_(angle, op === 'take' ? 800 : 400)].map(safeCell_));
  var q = tabRows_(QSHEET, QHEAD), i = -1;
  q.forEach(function (r, n) { if (r.id === id) i = n; });
  var up = q.filter(function (r) { return r.status === 'queued'; });
  if (op === 'add') q.push({ id: 'new', topic: clean_(topic, 200), status: 'queued', why: 'Suggested by you; added at the next run.' });
  else if (i >= 0 && op === 'dismiss') q.splice(i, 1);
  else if (i >= 0 && op === 'take') q[i].take = clean_(angle, 800);
  else if (i >= 0 && op === 'queue' && q[i].status !== 'queued') {   // to the end of Up next
    var iq = q.splice(i, 1)[0], last = -1;
    iq.status = 'queued';
    q.forEach(function (r, n) { if (r.status === 'queued') last = n; });
    q.splice(last + 1, 0, iq);
  }
  else if (i >= 0 && op === 'next') { var it = q.splice(i, 1)[0]; it.status = 'queued'; q.unshift(it); }
  else if (i >= 0 && (op === 'up' || op === 'down')) {
    var j = op === 'up' ? i - 1 : i + 1;
    if (j >= 0 && j < q.length && q[j].status === q[i].status) { var t = q[i]; q[i] = q[j]; q[j] = t; }
  }
  writeQueue_(q);
}

function queuePage_(t, note, pick, pop, ptopic) {
  var q = tabRows_(QSHEET, QHEAD), url = selfUrl_();
  var btn = function (op, id, label, primary) {
    return '<form method="post" action="' + url + '" target="_top" style="display:inline">' +
      '<input type="hidden" name="action" value="dd"><input type="hidden" name="t" value="' + esc_(t) + '">' +
      '<input type="hidden" name="op" value="' + op + '"><input type="hidden" name="id" value="' + esc_(id) + '">' +
      '<button style="margin:4px 6px 0 0;padding:7px 12px;border-radius:999px;border:1px solid #2c4a66;cursor:pointer;' +
      'font:inherit;font-size:13px;background:' + (primary ? '#67e6a8;color:#06221a' : '#112a42;color:#eff7ff') + '">' + label +
      '</button></form>';
  };
  var takeForm = function (r) {                      // Steven's own words, read verbatim after the deep dive
    return '<form method="post" action="' + url + '" target="_top" style="margin-top:6px">' +
      '<input type="hidden" name="action" value="dd"><input type="hidden" name="t" value="' + esc_(t) + '">' +
      '<input type="hidden" name="op" value="take"><input type="hidden" name="id" value="' + esc_(r.id) + '">' +
      '<textarea name="angle" maxlength="800" rows="2" placeholder="Your take (optional): read verbatim as Steven\'s take ' +
      'at the end of this deep dive" style="width:100%;box-sizing:border-box;padding:8px 10px;border-radius:10px;' +
      'border:1px solid #2c4a66;background:#07131f;color:#eff7ff;font:inherit;font-size:14px">' + esc_(r.take || '') +
      '</textarea><button style="margin-top:4px;padding:6px 12px;border-radius:999px;border:1px solid #2c4a66;' +
      'background:#112a42;color:#eff7ff;font:inherit;font-size:13px;cursor:pointer">Save my take</button></form>';
  };
  var row = function (r, n) {
    return '<div id="q-' + esc_(r.id) + '" style="padding:12px 0;border-top:1px solid #23415d"><b>' + (r.status === 'queued' ? (n + 1) + '. ' : '') +
      esc_(r.topic) + '</b>' + (r.why ? '<div style="font-size:13px;color:#9cc4df">' + esc_(r.why) + '</div>' : '') +
      (r.id === 'new' ? '' : '<div>' + (n === 0 && r.status === 'queued' ? '' : btn('next', r.id, 'Make next', true)) +
        (r.status === 'queued' ? btn('up', r.id, '↑') + btn('down', r.id, '↓') : btn('queue', r.id, '＋ Up next')) +
        btn('dismiss', r.id, 'Dismiss') + '</div>' + takeForm(r)) +
      '</div>';
  };
  var queued = q.filter(function (r) { return r.status === 'queued'; });
  var sugg = q.filter(function (r) { return r.status !== 'queued'; });
  var top = '';
  if (pick) {                                         // from an email link: one tap to confirm (links never change anything)
    var it = q.filter(function (r) { return r.id === pick; })[0];
    var ask = {next: ['Make <b>%</b> the next deep dive?', 'Yes, make it next'], up: ['Move <b>%</b> up?', 'Yes, move it up'],
      down: ['Move <b>%</b> down?', 'Yes, move it down'], queue: ['Add <b>%</b> to the end of Up next?', 'Yes, add it'],
      dismiss: ['Dismiss <b>%</b>?', 'Yes, dismiss it']}[pop || 'next'];
    if (it && pop === 'take') top = '<div style="padding:12px 14px;border-radius:14px;background:#10314a;margin-bottom:10px">' +
      'Your take on <b>' + esc_(it.topic) + '</b>' + takeForm(it) + '</div>';
    else if (it && ask) top = '<div style="padding:12px 14px;border-radius:14px;background:#10314a;margin-bottom:10px">' +
      ask[0].split('%').join(esc_(it.topic)) + '<div>' + btn(pop || 'next', it.id, ask[1], true) + '</div></div>';
  }
  var body = (note ? '<p style="color:#67e6a8">' + esc_(note) + '</p>' : '') + top +
    '<h3 style="margin:14px 0 4px">Up next</h3><p style="font-size:13px;color:#9cc4df;margin:0">The first one airs ' +
    'with the next briefing. Changes apply when the pipeline next runs.</p>' +
    (queued.map(row).join('') || '<p>Nothing queued: Claude picks the strongest suggestion.</p>') +
    '<h3 style="margin:18px 0 4px">Suggestions</h3>' + (sugg.map(function (r) { return row(r, 99); }).join('') || '<p>None.</p>') +
    '<h3 style="margin:18px 0 4px">Suggest a topic</h3><form method="post" action="' + url + '" target="_top">' +
    '<input type="hidden" name="action" value="dd"><input type="hidden" name="t" value="' + esc_(t) + '">' +
    '<input type="hidden" name="op" value="add">' +
    '<input name="topic" maxlength="200" required placeholder="Topic" value="' + esc_(ptopic || '') + '" style="width:100%;box-sizing:border-box;margin:4px 0;' +
    'padding:10px 12px;border-radius:12px;border:1px solid #2c4a66;background:#07131f;color:#eff7ff;font:inherit">' +
    '<textarea name="angle" maxlength="400" rows="2" placeholder="Angle (optional): what you want explained" ' +
    'style="width:100%;box-sizing:border-box;margin:4px 0;padding:10px 12px;border-radius:12px;border:1px solid #2c4a66;' +
    'background:#07131f;color:#eff7ff;font:inherit"></textarea>' +
    '<button style="margin-top:6px;padding:10px 18px;border:0;border-radius:999px;background:#67e6a8;color:#06221a;' +
    'font:inherit;font-weight:600;cursor:pointer">Add to Up next</button></form>';
  return page_('Deep-dive queue', body);
}

function stars_(n) {
  var o = '';
  for (var i = 1; i <= 5; i++) o += '<span style="color:' + (i <= n ? '#ffd166' : '#3b5874') + '">&#9733;</span>';
  return o;
}

function ratePage_(day, score, t) {
  var opts = '';
  for (var i = 1; i <= 5; i++) {
    opts += '<label style="cursor:pointer;font-size:44px;line-height:1;padding:0 2px">' +
      '<input type="radio" name="s" value="' + i + '"' + (i === score ? ' checked' : '') + ' required ' +
      'style="position:absolute;opacity:0;width:1px;height:1px" onchange="paint(' + i + ')">' +
      '<span class="st" data-i="' + i + '">&#9733;</span></label>';
  }
  var body = '<p>How was the briefing for <b>' + esc_(day) + '</b>?</p>' +
    '<form method="post" action="' + selfUrl_() + '" target="_top">' +
    '<input type="hidden" name="action" value="rate"><input type="hidden" name="d" value="' + esc_(day) + '">' +
    '<input type="hidden" name="t" value="' + esc_(t) + '">' +
    '<input type="text" name="website" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px">' +
    '<div style="margin:4px 0 14px">' + opts + '</div>' +
    '<label style="display:block;font-size:14px;color:#9cc4df;margin-bottom:6px">Optional: what would make it a 5?</label>' +
    '<textarea name="note" maxlength="600" rows="3" style="width:100%;box-sizing:border-box;font:inherit;font-size:15px;' +
    'padding:10px 12px;border-radius:14px;border:1px solid #2c4a66;background:#07131f;color:#eff7ff"></textarea>' +
    '<p><button type="submit" style="margin-top:12px;padding:11px 20px;border:0;border-radius:999px;background:#67e6a8;' +
    'color:#06221a;font:inherit;font-weight:600;cursor:pointer">Send rating</button></p></form>' +
    '<script>function paint(n){document.querySelectorAll(".st").forEach(function(e){e.style.color=' +
    '(+e.dataset.i<=n)?"#ffd166":"#3b5874";});}paint(' + (score || 0) + ');</script>';
  return page_('Rate today\'s briefing', body);
}

function rows_() {
  var sh = sheet_(), v = sh.getDataRange().getValues(), out = [];
  for (var i = 1; i < v.length; i++) {
    var r = {}; HEAD.forEach(function (h, j) { r[h] = v[i][j]; }); r._row = i + 1; out.push(r);
  }
  return out;
}

function find_(field, value) {
  value = String(value || '').toLowerCase();
  return rows_().filter(function (r) { return String(r[field]).toLowerCase() === value; })[0];
}

function put_(r) {
  var sh = sheet_(), vals = [HEAD.map(function (h) { return r[h] === undefined ? '' : r[h]; })];
  if (r._row) sh.getRange(r._row, 1, 1, HEAD.length).setValues(vals); else sh.appendRow(vals[0]);
}

function esc_(s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function now_() { return new Date().toISOString(); }
function token_() { return Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '').slice(0, 8); }
function validEmail_(e) { return /^[^\s@<>"']+@[^\s@<>"']+\.[^\s@<>"']{2,}$/.test(e) && e.length <= 200; }

function page_(title, body) {
  var html = '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + title +
    '</title><body style="margin:0;background:#07131f;color:#eff7ff;font:17px/1.6 \'Avenir Next\',\'Segoe UI\',sans-serif">' +
    '<div style="max-width:560px;margin:48px auto;padding:28px;border:1px solid rgba(177,222,255,.18);border-radius:24px;' +
    'background:#0c2236"><div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#9cc4df">AI Briefing</div>' +
    '<h1 style="font-size:26px;margin:8px 0 12px">' + title + '</h1>' + body +
    '<p><a href="' + site_() + '" style="display:inline-block;margin-top:10px;padding:10px 16px;border-radius:999px;' +
    'background:#67e6a8;color:#06221a;text-decoration:none;font-weight:600">Back to the AI Briefing</a></p></div></body>';
  return HtmlService.createHtmlOutput(html).setTitle(title);
}

function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

// ---- Drive: the folder the edition and deep dive are written to (Steven, 2026-10-26: to read and give feedback
// on, e.g. while driving). Script property DRIVE_FOLDER_ID, else the mailer account's folder named "Briefings".
function briefingsFolder_() {
  var id = props_().getProperty('DRIVE_FOLDER_ID');
  if (id) return DriveApp.getFolderById(id);
  var it = DriveApp.getFoldersByName('Briefings');
  if (!it.hasNext()) throw new Error('no Drive folder named Briefings');
  return it.next();
}

function docIn_(folder, name) {
  var it = folder.getFilesByName(name);
  while (it.hasNext()) { var f = it.next(); if (f.getMimeType() === MimeType.GOOGLE_DOCS && !f.isTrashed()) return f; }
  return null;
}

// One Google Doc per name: rewritten in place on a rerun (never deleted); REPLACE renames an earlier doc (the
// held draft becomes the published edition). Markdown: #/##/### headings, "- " bullets, **bold** and links as text.
function saveDoc_(name, replace, md) {
  var folder = briefingsFolder_();
  var f = docIn_(folder, name) || (replace ? docIn_(folder, replace) : null), doc;
  if (f) { doc = DocumentApp.openById(f.getId()); if (f.getName() !== name) f.setName(name); }
  else { doc = DocumentApp.create(name); DriveApp.getFileById(doc.getId()).moveTo(folder); }
  var body = doc.getBody();
  body.appendParagraph('');                          // clear() refuses when the doc ends with a list item (10-27)
  body.clear();
  var H = { '#': DocumentApp.ParagraphHeading.HEADING1, '##': DocumentApp.ParagraphHeading.HEADING2,
            '###': DocumentApp.ParagraphHeading.HEADING3 };
  var plain = function (t) {
    return t.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/\*([^*]+)\*/g, '$1').replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '$1 ($2)');
  };
  String(md).replace(/\r\n/g, '\n').split('\n').forEach(function (ln) {
    var m = /^(#{1,3})\s+(.*)$/.exec(ln), b = /^\s*[-*]\s+(.*)$/.exec(ln);
    if (m) body.appendParagraph(plain(m[2])).setHeading(H[m[1]]);
    else if (b) body.appendListItem(plain(b[1])).setGlyphType(DocumentApp.GlyphType.BULLET);
    else if (ln.trim()) body.appendParagraph(plain(ln));
  });
  try {                                              // the empty paragraph clear() leaves; Docs refuses to remove the
    if (body.getNumChildren() > 1 && !body.getChild(0).asText().getText()) body.getChild(0).removeFromParent();
  } catch (err) {}                                   // last paragraph of a section (10-27): harmless to keep it
  doc.saveAndClose();
  return { ok: true, id: doc.getId(), url: doc.getUrl() };
}

// Run once in the editor after deploying v0.2.11 (Run > authorizeDrive): grants Drive and Docs access.
function authorizeDrive() {
  Logger.log('Drive folder: ' + briefingsFolder_().getName() + ' · Docs OK: ' + !!DocumentApp.getActiveDocument);
}

function authed_(p) {
  var s = props_().getProperty('SECRET');
  return s && s.length >= 24 && p.key === s;
}

function confirmEmail_(r) {
  var link = selfUrl_() + '?action=confirm&t=' + r.token;
  var html = '<div style="background:#07131f;padding:24px 12px;font-family:\'Avenir Next\',\'Segoe UI\',Arial,sans-serif">' +
    '<div style="max-width:560px;margin:0 auto;background:#0c2236;border:1px solid #23415d;border-radius:20px;padding:26px;color:#eff7ff">' +
    '<div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#9cc4df">AI Briefing</div>' +
    '<h1 style="font-size:22px;margin:8px 0 12px;color:#eff7ff">Confirm your subscription</h1>' +
    '<p style="color:#d7ecff">Someone (hopefully you) asked to get the daily AI Briefing at this address. ' +
    'Click to confirm; nothing is sent until you do.</p>' +
    '<p><a href="' + link + '" style="display:inline-block;padding:11px 18px;border-radius:999px;background:#67e6a8;' +
    'color:#06221a;text-decoration:none;font-weight:600">Yes, send me the briefing</a></p>' +
    '<p style="font-size:13px;color:#9cc4df">If this wasn\'t you, ignore this email and you won\'t hear from us again.</p></div></div>';
  MailApp.sendEmail(r.email, 'Confirm: the daily AI Briefing', 'Confirm your subscription: ' + link +
    '\n\nIf this wasn\'t you, ignore this email.', mailOpts_({ htmlBody: html, name: fromName_() }));
}

function subscribe_(email, source, confirmed) {
  email = String(email || '').trim().toLowerCase();
  if (!validEmail_(email)) return { ok: false, error: 'invalid email' };
  var r = find_('email', email);
  if (r && r.status === 'active') return { ok: true, status: 'active', note: 'already subscribed' };
  var cache = CacheService.getScriptCache();
  confirmed = '';      // security (2026-10-15): nobody is activated without clicking the confirmation link
  if (cache.get('sub:' + email)) return { ok: true, status: 'pending', note: 'confirmation already sent' };
  // global limit on confirmation emails (stops the form being used to burn the quota or send spam)
  var n = Number(cache.get('confirms:hour') || '0');
  if (n >= 20) return { ok: false, error: 'busy, try again later' };
  if (MailApp.getRemainingDailyQuota() < rows_().filter(function (x) { return x.status === 'active'; }).length + 10)
    return { ok: false, error: 'busy, try again later' };
  cache.put('confirms:hour', String(n + 1), 3600);
  r = r || { email: email, created: now_() };
  r.token = r.token || token_();
  r.source = source;
  r.updated = now_();
  if (confirmed) { r.status = 'active'; r.confirmed = now_(); r.consent = 'Added by Steven: ' + confirmed; }
  else { r.status = 'pending'; r.consent = CONSENT; }
  put_(r);
  if (!confirmed) { confirmEmail_(r); cache.put('sub:' + email, '1', 600); }
  return { ok: true, status: r.status };
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.action === 'confirm' || p.action === 'unsubscribe') {
    var r = p.t && find_('token', p.t);
    if (!r) return page_('Link not recognised', '<p>This link is old or incomplete. You can sign up again on the briefing page.</p>');
    if (p.action === 'confirm') {
      if (r.status !== 'active') { r.status = 'active'; r.confirmed = now_(); r.updated = now_(); put_(r); }
      return page_('You\'re subscribed', '<p>The AI Briefing will arrive at <b>' + esc_(r.email) + '</b> each morning when it is published.</p>' +
        '<p style="color:#9cc4df;font-size:14px">Every email has a one-click unsubscribe link.</p>');
    }
    r.status = 'unsubscribed'; r.updated = now_(); put_(r);
    return page_('Unsubscribed', '<p><b>' + esc_(r.email) + '</b> won\'t get the AI Briefing by email any more.</p>' +
      '<p><a style="color:#d9f7ff" href="' + selfUrl_() + '?action=confirm&t=' + r.token + '">Changed your mind? Resubscribe</a></p>');
  }
  if (p.action === 'review') {                       // the held edition with a box per section (owner token t only)
    if (!ownerOf_(p.t, 't')) return page_('Link not recognised', '<p>This link only works from your own takes email, ' +
      'and expires after two days.</p>');
    if (!validDay_(p.d)) return page_('Link not recognised', '<p>Unknown day.</p>');
    var rv = tab_(VSHEET, VHEAD).getDataRange().getValues(), parts = [];
    for (var ri = 1; ri < rv.length; ri++) if (dayStr_(rv[ri][0]) === String(p.d)) parts.push([Number(rv[ri][1]), String(rv[ri][2])]);
    if (!parts.length) return page_('Not ready', '<p>The review page for ' + esc_(p.d) + ' isn\'t here yet. Reply to the takes email instead.</p>');
    parts.sort(function (a, b) { return a[0] - b[0]; });
    var body = parts.map(function (x) { return x[1]; }).join('').split('{{SCRIPT}}').join(selfUrl_()).split('{{T}}').join(esc_(String(p.t)));
    return HtmlService.createHtmlOutput(body).setTitle('Your takes · ' + p.d)
      .addMetaTag('viewport', 'width=device-width, initial-scale=1');
  }
  if (p.action === 'queue') {
    if (!isOwnerToken_(p.t)) return page_('Link not recognised', '<p>This link only works from your own evening note.</p>');
    return queuePage_(String(p.t), '', clean_(p.pick, 20), clean_(p.op, 10), clean_(p.topic, 200));
  }
  if (p.action === 'rate') {
    if (!validDay_(p.d)) return page_('Link not recognised', '<p>This rating link is old or incomplete.</p>');
    var sub = rater_(p.t);
    if (p.t && !sub) return page_('Link not recognised', '<p>This rating link is old or incomplete.</p>');
    var sc = parseInt(p.s, 10);
    return ratePage_(String(p.d), (sc >= 1 && sc <= 5) ? sc : 0, sub ? String(p.t) : '');
  }
  return page_('AI Briefing', '<p>Sign up on the <a style="color:#d9f7ff" href="' + site_() + '">briefing page</a>.</p>');
}

/** Run this once from the editor (choose checkSetup, click Run): it touches the Sheet and the mail quota,
 *  so Google asks for every permission the web app needs, and the log shows what is set up. */
function checkSetup() {
  var s = props_().getProperty('SECRET') || '';
  Logger.log('SECRET set: ' + (s.length >= 24 ? 'yes (' + s.length + ' chars)' : 'NO / too short'));
  Logger.log('SITE_URL: ' + site_());
  Logger.log('SHEET_ID: ' + (props_().getProperty('SHEET_ID') || '(none: bound to its own Sheet)'));
  Logger.log('OWNER_EMAIL: ' + owners_().join(', ') + ' · REPLY_TO: ' + (replyTo_() || '(not set)'));
  Logger.log('Sending as: ' + Session.getEffectiveUser().getEmail());
  Logger.log('Sheet rows: ' + rows_().length + ' subscriber(s) in "' + SHEET + '"');
  Logger.log('Ratings: ' + rrows_().length + ' in "' + RSHEET + '"');
  Logger.log('Mail quota left today: ' + MailApp.getRemainingDailyQuota());
  Logger.log('Web app URL: ' + selfUrl_());
}

function doPost(e) {
  try { return doPost_(e); }
  catch (err) { return json_({ ok: false, error: 'script error: ' + err }); }
}

function doPost_(e) {
  var p = (e && e.parameter) || {};
  if (p.action === 'subscribe') {                    // public form on the landing page
    if (p.website) return page_('Thanks', '<p>Check your inbox.</p>');      // honeypot: bots fill every field
    var res = subscribe_(p.email, 'site', '');
    if (!res.ok) return page_('That address didn\'t look right', '<p>Please go back and check the email address.</p>');
    if (res.status === 'active') return page_('You\'re already subscribed', '<p>The briefing already goes to that address.</p>');
    return page_('Check your inbox', '<p>We sent a confirmation link to <b>' + esc_(String(p.email).trim()) +
      '</b>. Click it and the briefing starts with the next edition.</p>' +
      '<p style="color:#9cc4df;font-size:14px">Nothing arrives? Check spam, or sign up again in ten minutes.</p>');
  }
  if (p.action === 'dd') {                            // the queue page's buttons: owner token only
    if (!isOwnerToken_(p.t)) return page_('Link not recognised', '<p>This link only works from your own evening note.</p>');
    var op = String(p.op || '');
    if (['next', 'up', 'down', 'dismiss', 'add', 'queue', 'take'].indexOf(op) < 0) return page_('That didn\'t work', '<p>Unknown action.</p>');
    if (op === 'add' && !clean_(p.topic, 200)) return queuePage_(String(p.t), 'Type a topic first.', '');
    queueAction_(op, String(p.id || ''), p.topic, p.angle);
    return queuePage_(String(p.t), {next: 'Done: that airs next.', up: 'Moved up.', down: 'Moved down.',
      dismiss: 'Dismissed.', add: 'Added to Up next.', queue: 'Added to the end of Up next.',
      take: clean_(p.angle, 800) ? 'Your take is saved: read after the deep dive when it airs.' : 'Your take is cleared.'}[op], '');
  }
  if (p.action === 'rate') {                          // the confirm page above; public, token optional
    if (p.website) return page_('Thanks', '<p>Thanks.</p>');
    var sc = parseInt(p.s, 10);
    if (!validDay_(p.d) || !(sc >= 1 && sc <= 5)) return page_('That didn\'t work', '<p>Pick 1 to 5 stars and send again.</p>');
    var sub = rater_(p.t);
    if (p.t && !sub) return page_('Link not recognised', '<p>This rating link is old or incomplete.</p>');
    if (!sub) {                                      // anonymous site stars: a global hourly cap
      var cache = CacheService.getScriptCache(), n = Number(cache.get('webrate:hour') || '0');
      if (n >= 60) return page_('Thanks', '<p>Thanks: we have plenty of ratings this hour.</p>');
      cache.put('webrate:hour', String(n + 1), 3600);
    }
    saveRating_(String(p.d), sc, p.note, sub);
    return page_('Thanks for rating', '<p style="font-size:34px;margin:0 0 6px">' + stars_(sc) + '</p>' +
      '<p>Your rating for ' + esc_(p.d) + ' is in' + (sub ? '; clicking again replaces it.' : '.') + '</p>' +
      '<p style="color:#9cc4df;font-size:14px">Know someone who would like it? Forward the email or share ' +
      '<a style="color:#d9f7ff" href="' + site_() + esc_(p.d) + '/">today\'s page</a>.</p>');
  }
  if (p.action === 'takes') {                         // Steven's takes from the site page: owner token (scope t) only
    if (!ownerOf_(p.t, 't')) return page_('Link not recognised', '<p>This link only works from your own takes email, ' +
      'and expires after two days.</p>');
    if (!validDay_(p.d)) return page_('That didn\'t work', '<p>Unknown day.</p>');
    var tk = {};
    try { tk = JSON.parse(String(p.takes || '{}')); } catch (err) { tk = {}; }
    Object.keys(p).forEach(function (k) { if (/^s_(\d{1,2}|T|W)$/i.test(k) && String(p[k]).trim()) tk[k.slice(2)] = p[k]; });
    var sh = tab_(TSHEET, THEAD), n = 0, done = String(p.done || '') === '1', at = isoStr_(new Date());
    var put = function (row) {                       // as text: Sheets would turn "2026-10-25" into a date cell
      sh.getRange(sh.getLastRow() + 1, 1, 1, THEAD.length).setNumberFormat('@').setValues([row.map(safeCell_)]);
    };
    Object.keys(tk).slice(0, 20).forEach(function (k) {
      var slot = String(k).toUpperCase().slice(0, 2), text = clean_(tk[k], 1500);
      if (!/^(\d{1,2}|T|W)$/.test(slot) || !text) return;
      put([at, String(p.d), slot, text, '']);
      n++;
    });
    if (done) put([at, String(p.d), 'DONE', '', '1']);
    return page_('Takes saved', '<p>' + n + ' take' + (n === 1 ? '' : 's') + ' saved for ' + esc_(p.d) +
      (done ? '. The edition goes out within a few minutes.' : '. The edition goes out at the cutoff, or when you send done.') +
      '</p><p style="color:#9cc4df;font-size:14px">Anything with a private name or detail is held back and listed to you, ' +
      'never published. Submitting again replaces a take for the same section.</p>');
  }
  if (!authed_(p)) return json_({ ok: false, error: 'unauthorised' });
  if (p.action === 'savedoc') {                     // the edition and deep dive as Google Docs in Drive (key only)
    var dn = clean_(p.name, 200), dt = String(p.text || '');
    if (!dn || !dt || dt.length > 300000) return json_({ ok: false, error: 'bad doc' });
    return json_(saveDoc_(dn, clean_(p.replace, 200), dt));
  }
  if (p.action === 'setreview') {                   // the pipeline uploads the held edition's review page (key only)
    if (!validDay_(p.d)) return json_({ ok: false, error: 'bad day' });
    var html = String(p.html || '');
    if (!html || html.length > 450000) return json_({ ok: false, error: 'bad page' });
    var vs = tab_(VSHEET, VHEAD);
    if (vs.getLastRow() > 1) vs.getRange(2, 1, vs.getLastRow() - 1, VHEAD.length).clearContent();   // only the latest day
    var rows = [];
    for (var i = 0; i * 40000 < html.length; i++) rows.push([String(p.d), String(i), html.slice(i * 40000, (i + 1) * 40000)]);
    vs.getRange(2, 1, rows.length, VHEAD.length).setNumberFormat('@').setValues(rows);
    return json_({ ok: true, parts: rows.length });
  }
  if (p.action === 'takes_pull') {                  // the pipeline reads the day's site takes (key only)
    var tv = tab_(TSHEET, THEAD).getDataRange().getValues(), tout = [];
    for (var ti = 1; ti < tv.length; ti++) {         // raw values: a day may be a date cell (rows before v0.2.9)
      if (dayStr_(tv[ti][1]) !== String(p.d)) continue;
      tout.push({ at: isoStr_(tv[ti][0]), slot: String(tv[ti][2]), text: String(tv[ti][3] || ''), done: String(tv[ti][4]) === '1' });
    }
    return json_({ ok: true, takes: tout });
  }
  if (p.action === 'setqueue') {                    // the pipeline's queue snapshot for the page
    var rows = [];
    try { rows = JSON.parse(String(p.items || '[]')); } catch (err) { return json_({ ok: false, error: 'bad items' }); }
    writeQueue_(rows.slice(0, 40));
    return json_({ ok: true, n: rows.length });
  }
  if (p.action === 'ddactions') return json_({ ok: true, actions: tabRows_(ASHEET, AHEAD) });
  if (p.action === 'ratings') {                     // read-only export for the scorecard: never addresses
    return json_({ ok: true, ratings: rrows_().map(function (r) {
      var id = r.email ? Utilities.base64EncodeWebSafe(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
        String(r.email) + '|' + props_().getProperty('SECRET'))).slice(0, 12) : '';
      return { day: dayStr_(r.day), who: r.who, score: Number(r.score), note: String(r.note || ''), at: isoStr_(r.at), src: r.src, id: id };
    }) });
  }
  if (p.action === 'list') {
    return json_({ ok: true, quota: MailApp.getRemainingDailyQuota(), subscribers: rows_().map(function (r) {
      return { email: r.email, status: r.status, created: r.created, confirmed: r.confirmed, updated: r.updated, source: r.source };
    }) });
  }
  if (p.action === 'add') return json_(subscribe_(p.email, p.source === 'terminal' ? 'terminal' : 'dashboard', p.confirmed || ''));
  if (p.action === 'remove') {
    var r = find_('email', p.email);
    if (!r) return json_({ ok: false, error: 'not found' });
    r.status = 'unsubscribed'; r.updated = now_(); put_(r);
    return json_({ ok: true, status: r.status });
  }
  if (p.action === 'send') {
    if (!/^AI Briefing/.test(String(p.subject || ''))) return json_({ ok: false, error: 'subject not allowed' });
    // p.html / p.text contain {{UNSUBSCRIBE}} and {{RATE}} (the recipient's rating link, + "&s=N");
    // p.to = one address (test) or empty for every active subscriber
    var to = String(p.to || '').toLowerCase().trim();
    if (to) {
      var sub = find_('email', to);
      if (owners_().indexOf(to) < 0 && !(sub && sub.status === 'active')) return json_({ ok: false, error: 'recipient not allowed' });
    }
    var targets = to ? [find_('email', to) || { email: to, token: '' }]
                     : rows_().filter(function (r) { return r.status === 'active'; });
    var quota = MailApp.getRemainingDailyQuota();
    if (targets.length > quota) return json_({ ok: false, error: 'daily quota too low', quota: quota, needed: targets.length });
    var sent = 0, failed = [];
    targets.forEach(function (r) {
      var un = r.token ? selfUrl_() + '?action=unsubscribe&t=' + r.token : site_();
      var rt = r.token || (owners_().indexOf(String(r.email).toLowerCase()) >= 0 ? ownerToken_(r.email, 'r') : '');
      var rate = selfUrl_() + '?action=rate&d=' + encodeURIComponent(validDay_(p.day) ? p.day : '') + (rt ? '&t=' + rt : '');
      var isOwner = owners_().indexOf(String(r.email).toLowerCase()) >= 0;
      var own = isOwner ? ownerToken_(r.email, 'q') : '';
      var ownt = isOwner ? ownerToken_(r.email, 't') : '';
      var fill = function (x) { return String(x || '').split('{{UNSUBSCRIBE}}').join(un).split('{{RATE}}').join(rate)
        .split('{{OWNERT}}').join(ownt).split('{{OWNER}}').join(own).split('{{SCRIPT}}').join(selfUrl_()); };
      try {
        MailApp.sendEmail(r.email, p.subject, fill(p.text), mailOpts_({ htmlBody: fill(p.html), name: fromName_() }));
        sent++;
      } catch (err) { failed.push(r.email + ': ' + err); }
    });
    return json_({ ok: failed.length === 0, sent: sent, failed: failed, quota: MailApp.getRemainingDailyQuota() });
  }
  return json_({ ok: false, error: 'unknown action' });
}

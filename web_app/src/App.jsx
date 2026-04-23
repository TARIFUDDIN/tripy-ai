import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

/* ─── Google Fonts injected once ────────────────────────────────────────────── */
const FontInjector = () => {
  useEffect(() => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300&display=swap';
    document.head.appendChild(link);
  }, []);
  return null;
};

/* ─── Inline global styles ───────────────────────────────────────────────────── */
const STYLES = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #0a0d12;
    --surface:   #111520;
    --surface2:  #161b28;
    --border:    rgba(255,255,255,0.07);
    --border2:   rgba(255,255,255,0.12);
    --accent:    #4f8ef7;
    --accent2:   #7c5cfc;
    --gold:      #f0c040;
    --green:     #34d399;
    --red:       #f87171;
    --muted:     rgba(255,255,255,0.35);
    --text:      #e8edf5;
    --text2:     rgba(232,237,245,0.7);
    --font-head: 'Syne', sans-serif;
    --font-body: 'DM Sans', sans-serif;
    --radius:    14px;
    --radius-sm: 8px;
    --shadow:    0 8px 32px rgba(0,0,0,0.5);
  }

  html, body, #root {
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-body);
    font-size: 15px;
    line-height: 1.6;
  }

  /* ── Layout ── */
  .app { display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

  /* ── Header ── */
  .app-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 28px; height: 60px; flex-shrink: 0;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    backdrop-filter: blur(12px);
    position: relative; z-index: 10;
  }
  .header-brand { display: flex; align-items: center; gap: 10px; }
  .brand-icon { font-size: 22px; }
  .brand-name {
    font-family: var(--font-head); font-weight: 800; font-size: 19px;
    background: linear-gradient(135deg, #4f8ef7, #7c5cfc);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    letter-spacing: -0.3px;
  }
  .brand-tag {
    font-size: 11px; color: var(--muted); font-weight: 300; letter-spacing: 0.5px;
    text-transform: uppercase; margin-left: 4px;
  }
  .header-pills { display: flex; gap: 8px; }
  .pill {
    padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 500;
    letter-spacing: 0.3px; border: 1px solid var(--border2);
    background: rgba(255,255,255,0.04); color: var(--muted);
  }

  /* ── Chat area ── */
  .chat-area {
    flex: 1; overflow-y: auto; padding: 24px 0 8px;
    scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent;
  }
  .chat-area::-webkit-scrollbar { width: 5px; }
  .chat-area::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }

  .msg-row { display: flex; gap: 12px; padding: 6px 24px; animation: fadeUp .3s ease both; }
  .msg-row.user { flex-direction: row-reverse; }
  @keyframes fadeUp { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }

  .avatar {
    width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; margin-top: 2px;
    background: linear-gradient(135deg, #1e2a45, #2a1e45);
    border: 1px solid var(--border2);
  }

  .bubble {
    max-width: 720px; border-radius: var(--radius);
    font-size: 14.5px; line-height: 1.65;
  }
  .bubble.user {
    background: linear-gradient(135deg, #1b2d55, #22194a);
    border: 1px solid rgba(79,142,247,0.25);
    padding: 12px 18px; color: var(--text);
  }
  .bubble.plain {
    background: var(--surface); border: 1px solid var(--border);
    padding: 14px 18px; color: var(--text2);
  }
  .bubble.rich { background: transparent; padding: 0; width: 100%; max-width: 900px; }

  /* ── Typing indicator ── */
  .typing { display: flex; gap: 5px; padding: 16px 18px; background: var(--surface); border-radius: var(--radius); border: 1px solid var(--border); }
  .typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); opacity: 0.3; animation: blink 1.2s infinite; }
  .typing span:nth-child(2) { animation-delay: .2s; }
  .typing span:nth-child(3) { animation-delay: .4s; }
  @keyframes blink { 0%,80%,100%{opacity:.3} 40%{opacity:1} }

  /* ── Trip Header card ── */
  .trip-card {
    background: linear-gradient(135deg, #0f1928, #14102a);
    border: 1px solid var(--border2); border-radius: var(--radius);
    padding: 20px 24px; margin-bottom: 12px;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
    position: relative; overflow: hidden;
  }
  .trip-card::before {
    content:''; position:absolute; inset:0;
    background: radial-gradient(ellipse at 30% 50%, rgba(79,142,247,0.07) 0%, transparent 70%);
    pointer-events: none;
  }
  .trip-route { display: flex; align-items: center; gap: 10px; }
  .trip-city { font-family: var(--font-head); font-size: 22px; font-weight: 800; letter-spacing:-0.5px; }
  .trip-origin { color: #7ab3ff; }
  .trip-dest   { color: #c49fff; }
  .trip-arrow-wrap {
    display: flex; flex-direction: column; align-items: center; gap: 2px;
  }
  .trip-arrow { color: var(--muted); font-size: 18px; }
  .stops-hint { font-size: 10px; color: var(--muted); letter-spacing: 0.3px; white-space: nowrap; }
  .trip-meta { display: flex; gap: 18px; flex-wrap: wrap; }
  .meta-item { display: flex; flex-direction: column; gap: 2px; }
  .meta-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; }
  .meta-val { font-size: 14px; font-weight: 500; color: var(--text); }

  /* ── Section blocks ── */
  .section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 12px; overflow: hidden;
  }
  .section-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 20px; border-bottom: 1px solid var(--border);
    background: rgba(255,255,255,0.02);
  }
  .section-title {
    font-family: var(--font-head); font-size: 15px; font-weight: 700;
    display: flex; align-items: center; gap: 8px; letter-spacing: -0.2px;
  }
  .section-icon { font-size: 16px; }

  /* ── Data note badges ── */
  .data-badge {
    font-size: 10.5px; font-weight: 600; padding: 3px 10px; border-radius: 20px;
    letter-spacing: 0.4px; text-transform: uppercase;
  }
  .est-badge   { background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid var(--border); }
  .sched-badge { background: rgba(79,142,247,0.12); color: var(--accent); border: 1px solid rgba(79,142,247,0.3); }

  /* ── Flight cards ── */
  .flights-list { display: flex; flex-direction: column; }
  .flight-card {
    display: grid;
    grid-template-columns: 28px 200px 1fr 1fr 90px 80px 100px 90px;
    align-items: center; gap: 12px;
    padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    transition: background .15s;
    cursor: default;
  }
  .flight-card:last-child { border-bottom: none; }
  .flight-card:hover { background: rgba(255,255,255,0.025); }
  .flight-card.best { background: rgba(79,142,247,0.06); }
  .flight-card.best:hover { background: rgba(79,142,247,0.09); }

  .rank { font-family: var(--font-body); font-size: 14px; font-weight: 700; color: var(--muted); }
  .rank.r1 { color: var(--gold); }

  .airline-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .airline-logo-wrap {
    width: 36px; height: 36px; border-radius: 8px; flex-shrink: 0;
    background: rgba(255,255,255,0.06); border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center; overflow: hidden;
  }
  .airline-logo-wrap img { width: 28px; height: 28px; object-fit: contain; }
  .airline-logo-wrap .airline-initials { font-size: 11px; font-weight: 700; color: var(--accent); letter-spacing: -.3px; }
  .airline-info { min-width: 0; }
  .airline-name { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .flight-num { font-size: 11.5px; color: var(--muted); font-family: monospace; }

  .time-block { display: flex; flex-direction: column; gap: 2px; }
  .time-val { font-size: 16px; font-weight: 600; font-family: var(--font-body); letter-spacing: 0; }
  .time-label { font-size: 10.5px; color: var(--muted); }

  .duration-cell { display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .dur-line { display: flex; align-items: center; gap: 6px; }
  .dur-dash { flex: 1; height: 1px; background: var(--border2); min-width: 30px; }
  .dur-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
  .dur-val { font-size: 12.5px; color: var(--text2); font-weight: 500; white-space: nowrap; }
  .via-tag { font-size: 10px; color: var(--muted); }

  .stops-cell { text-align: center; }
  .stop-chip {
    display: inline-block; font-size: 11px; font-weight: 600;
    padding: 3px 9px; border-radius: 20px;
  }
  .stop-chip.nonstop { background: rgba(52,211,153,0.12); color: var(--green); border: 1px solid rgba(52,211,153,0.25); }
  .stop-chip.one-stop { background: rgba(240,192,64,0.1); color: var(--gold); border: 1px solid rgba(240,192,64,0.25); }
  .stop-chip.multi   { background: rgba(248,113,113,0.1); color: var(--red);  border: 1px solid rgba(248,113,113,0.25); }

  .price-cell { text-align: right; }
  .price-val { font-family: var(--font-body); font-size: 18px; font-weight: 700; color: var(--text); letter-spacing: 0; }
  .price-sub { font-size: 10.5px; color: var(--muted); }

  .status-cell { display: flex; justify-content: center; }
  .status-chip {
    font-size: 9.5px; font-weight: 700; padding: 3px 8px; border-radius: 20px;
    letter-spacing: 0.5px; text-transform: uppercase;
  }
  .status-chip.est   { background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid var(--border); }
  .status-chip.sched { background: rgba(79,142,247,0.1);   color: var(--accent);border: 1px solid rgba(79,142,247,0.3); }

  .carbon-cell { font-size: 11px; color: var(--muted); text-align: right; }

  .flight-header {
    display: grid;
    grid-template-columns: 28px 200px 1fr 1fr 90px 80px 100px 90px;
    gap: 12px; padding: 9px 20px;
    border-bottom: 1px solid var(--border);
    background: rgba(0,0,0,0.2);
  }
  .col-head { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; color: var(--muted); font-weight: 600; }
  .col-right { text-align: right; }
  .col-center { text-align: center; }

  /* ── Hotel cards ── */
  .hotels-grid { display: flex; flex-direction: column; }
  .hotel-card {
    display: grid; grid-template-columns: 28px 1fr 90px 130px 100px 80px;
    align-items: center; gap: 14px; padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    transition: background .15s;
  }
  .hotel-card:last-child { border-bottom: none; }
  .hotel-card:hover { background: rgba(255,255,255,0.025); }
  .hotel-card.best { background: rgba(79,142,247,0.05); }

  .hotel-info { min-width: 0; }
  .hotel-name { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .hotel-src  { font-size: 11px; color: var(--muted); margin-top: 2px; }

  .cat-chip {
    font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px;
    white-space: nowrap;
  }
  .cat-chip.s2 { background: rgba(255,255,255,0.06); color: var(--muted); border: 1px solid var(--border); }
  .cat-chip.s3 { background: rgba(79,142,247,0.1); color: #8ab8ff; border: 1px solid rgba(79,142,247,0.25); }
  .cat-chip.s4 { background: rgba(124,92,252,0.1); color: #b39bff; border: 1px solid rgba(124,92,252,0.25); }
  .cat-chip.s5 { background: rgba(240,192,64,0.1); color: var(--gold);  border: 1px solid rgba(240,192,64,0.25); }

  .stars-row { display: flex; align-items: center; gap: 4px; }
  .star-fill { color: var(--gold); font-size: 13px; }
  .star-empty { color: rgba(255,255,255,0.15); font-size: 13px; }
  .rating-num { font-size: 12px; color: var(--text2); margin-left: 2px; font-weight: 500; }

  .hotel-header {
    display: grid; grid-template-columns: 28px 1fr 90px 130px 100px 80px;
    gap: 14px; padding: 9px 20px;
    border-bottom: 1px solid var(--border);
    background: rgba(0,0,0,0.2);
  }

  /* ── Activity cards ── */
  .activities-list { display: flex; flex-direction: column; }
  .activity-card {
    display: grid; grid-template-columns: 28px 1fr 90px 80px;
    align-items: start; gap: 14px; padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    transition: background .15s;
  }
  .activity-card:last-child { border-bottom: none; }
  .activity-card:hover { background: rgba(255,255,255,0.02); }

  .activity-name { font-weight: 600; font-size: 14px; margin-bottom: 3px; }
  .activity-desc { font-size: 12.5px; color: var(--muted); line-height: 1.5; }

  .act-header {
    display: grid; grid-template-columns: 28px 1fr 90px 80px;
    gap: 14px; padding: 9px 20px;
    border-bottom: 1px solid var(--border);
    background: rgba(0,0,0,0.2);
  }

  .price-tag {
    font-weight: 700; font-size: 14px;
    color: var(--text);
  }
  .price-free { color: var(--green); }

  /* ── Budget card ── */
  .budget-section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); overflow: hidden; margin-bottom: 12px;
  }
  .budget-rows { padding: 16px 20px; display: flex; flex-direction: column; gap: 10px; }
  .budget-row {
    display: flex; align-items: center; justify-content: space-between;
    font-size: 14px;
  }
  .budget-row .b-label { color: var(--text2); }
  .budget-row .b-val   { font-weight: 600; }
  .budget-divider { height: 1px; background: var(--border); margin: 4px 0; }
  .budget-total .b-label { font-family: var(--font-body); font-weight: 700; color: var(--text); font-size: 15px; }
  .budget-total .b-val   { font-family: var(--font-body); font-size: 18px; font-weight: 700; }
  .budget-total.fits .b-val { color: var(--green); }
  .budget-total.over .b-val { color: var(--red); }
  .budget-badge {
    padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 600;
  }
  .budget-badge.fits { background: rgba(52,211,153,0.12); color: var(--green); border: 1px solid rgba(52,211,153,0.3); }
  .budget-badge.over { background: rgba(248,113,113,0.1); color: var(--red);   border: 1px solid rgba(248,113,113,0.3); }

  /* ── Recommendation ── */
  .rec-card {
    background: linear-gradient(135deg, #0d1b30, #130d28);
    border: 1px solid rgba(79,142,247,0.2); border-radius: var(--radius);
    padding: 20px 24px; margin-bottom: 12px; position: relative; overflow: hidden;
  }
  .rec-card::before {
    content:''; position:absolute; top:-40px; right:-40px;
    width: 150px; height: 150px; border-radius: 50%;
    background: radial-gradient(circle, rgba(124,92,252,0.12), transparent 70%);
  }
  .rec-title {
    font-family: var(--font-head); font-size: 14px; font-weight: 700;
    color: var(--accent); margin-bottom: 10px;
    display: flex; align-items: center; gap: 7px;
  }
  .rec-body { font-size: 14px; color: var(--text2); line-height: 1.7; }

  /* ── Suggestions ── */
  .suggestions {
    padding: 8px 24px 0; display: flex; gap: 8px; flex-wrap: wrap;
  }
  .sug-btn {
    padding: 8px 16px; border-radius: 20px; font-size: 13px; font-weight: 500;
    background: rgba(255,255,255,0.04); border: 1px solid var(--border2);
    color: var(--text2); cursor: pointer; transition: all .15s;
    font-family: var(--font-body);
  }
  .sug-btn:hover {
    background: rgba(79,142,247,0.1); border-color: rgba(79,142,247,0.3);
    color: var(--text); transform: translateY(-1px);
  }

  /* ── Input area ── */
  .input-wrap {
    flex-shrink: 0; padding: 12px 24px 16px;
    border-top: 1px solid var(--border);
    background: var(--surface);
  }
  .input-inner {
    display: flex; gap: 10px; align-items: flex-end;
    background: var(--surface2); border: 1px solid var(--border2);
    border-radius: 16px; padding: 10px 12px 10px 18px;
    transition: border-color .15s;
  }
  .input-inner:focus-within { border-color: rgba(79,142,247,0.4); }
  .chat-input {
    flex: 1; resize: none; background: transparent; border: none; outline: none;
    color: var(--text); font-family: var(--font-body); font-size: 14.5px;
    line-height: 1.55; min-height: 22px; max-height: 110px;
  }
  .chat-input::placeholder { color: var(--muted); }
  .send-btn {
    width: 36px; height: 36px; border-radius: 10px; border: none; cursor: pointer;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    color: #fff; font-size: 16px; display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; transition: opacity .15s, transform .1s;
  }
  .send-btn:hover:not(:disabled) { opacity: .88; transform: scale(1.04); }
  .send-btn:disabled { opacity: .35; cursor: default; }

  /* ── Scrollbar polish for chat ── */
  .chat-area::-webkit-scrollbar { width: 4px; }
  .chat-area::-webkit-scrollbar-track { background: transparent; }
  .chat-area::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 4px; }

  /* ── Responsive ── */
  @media (max-width: 700px) {
    .flight-card, .flight-header { grid-template-columns: 20px 1fr 1fr 80px; }
    .col-dur, .col-status, .col-carbon, .dur-cell, .status-cell, .carbon-cell { display: none; }
    .hotel-card, .hotel-header { grid-template-columns: 20px 1fr 100px 70px; }
    .h-cat, .h-src { display: none; }
    .activity-card, .act-header { grid-template-columns: 20px 1fr 80px; }
    .a-dur { display: none; }
    .trip-meta { display: none; }
  }
`;

/* ─── Helpers ────────────────────────────────────────────────────────────────── */
const fmt = (v) => (v === null || v === undefined || v === '—' ? '—' : v);

function starsEl(rating) {
  if (!rating) return <span style={{color:'var(--muted)'}}>—</span>;
  const full = Math.floor(rating);
  const half = rating - full >= 0.4;
  const empty = Math.max(0, 5 - full - (half ? 1 : 0));
  return (
    <div className="stars-row">
      {'★'.repeat(full).split('').map((s,i) => <span key={i} className="star-fill">{s}</span>)}
      {half && <span className="star-fill" style={{opacity:.6}}>½</span>}
      {'☆'.repeat(empty).split('').map((s,i) => <span key={i} className="star-empty">{s}</span>)}
      <span className="rating-num">{rating}</span>
    </div>
  );
}

function catChip(cat) {
  const stars = parseInt(cat) || 3;
  const cls = ['','','s2','s3','s4','s5'][Math.min(stars,5)];
  return <span className={`cat-chip ${cls}`}>{cat}</span>;
}

function stopChip(stops) {
  if (stops === 0 || stops === '0') return <span className="stop-chip nonstop">Non-stop</span>;
  if (stops === 1)                  return <span className="stop-chip one-stop">1 Stop</span>;
  return <span className="stop-chip multi">{stops} Stops</span>;
}

// ✅ Only EST and SCHED — no LIVE
function statusChip(status) {
  if (status === 'real_schedule') return <span className="status-chip sched">SCHED</span>;
  return <span className="status-chip est">EST</span>;
}

function AirlineLogo({ airline, logoUrl }) {
  const [imgErr, setImgErr] = useState(false);
  const initials = (airline || '??').split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase();

  return (
    <div className="airline-logo-wrap">
      {logoUrl && !imgErr
        ? <img src={logoUrl} alt={airline} onError={() => setImgErr(true)} />
        : <span className="airline-initials">{initials}</span>
      }
    </div>
  );
}

function priceTag(price, isFree = false) {
  if (!price || price === '—') return <span className="price-tag" style={{color:'var(--muted)'}}>—</span>;
  if (isFree || price.toLowerCase().includes('free'))
    return <span className="price-tag price-free">Free</span>;
  return <span className="price-tag">{price}</span>;
}

/* ─── Trip Header ─────────────────────────────────────────────────────────────── */
function TripHeader({ trip }) {
  if (!trip) return null;
  const depDate = trip.departure_date ? new Date(trip.departure_date + 'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : '—';
  const retDate = trip.return_date   ? new Date(trip.return_date   + 'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short'}) : null;
  return (
    <div className="trip-card" style={{marginBottom:12}}>
      <div className="trip-route">
        <span className="trip-city trip-origin">{trip.origin || '?'}</span>
        <div className="trip-arrow-wrap">
          <span className="trip-arrow">→</span>
        </div>
        <span className="trip-city trip-dest">{trip.destination}</span>
      </div>
      <div className="trip-meta">
        <div className="meta-item">
          <span className="meta-label">Departs</span>
          <span className="meta-val">📅 {depDate}{retDate ? ` → ${retDate}` : ''}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Travellers</span>
          <span className="meta-val">👤 {trip.adults} adult{trip.adults > 1 ? 's' : ''}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Class</span>
          <span className="meta-val">💺 {trip.travel_class}</span>
        </div>
      </div>
    </div>
  );
}

/* ─── Flight Section ──────────────────────────────────────────────────────────── */
function FlightSection({ flights, note }) {
  if (!flights?.length) return null;

  // ✅ No LIVE badge — only Estimated or Scheduled
  const noteEl = note === 'real_schedule'
    ? <span className="data-badge sched-badge">🔵 Scheduled</span>
    : <span className="data-badge est-badge">⚪ Estimated</span>;

  return (
    <div className="section" style={{marginBottom:12}}>
      <div className="section-head">
        <div className="section-title"><span className="section-icon">✈️</span> Flights</div>
        {noteEl}
      </div>
      <div className="flight-header">
        <span className="col-head">#</span>
        <span className="col-head">Airline</span>
        <span className="col-head">Departure</span>
        <span className="col-head">Arrival</span>
        <span className="col-head col-center col-dur">Duration</span>
        <span className="col-head col-center">Stops</span>
        <span className="col-head col-right">Price</span>
        <span className="col-head col-center">Status</span>
      </div>
      <div className="flights-list">
        {flights.map((f, i) => {
          const via = f.terminal && f.terminal.startsWith('via') ? f.terminal : null;
          return (
            <div key={i} className={`flight-card ${i === 0 ? 'best' : ''}`}>
              <span className={`rank ${i === 0 ? 'r1' : ''}`}>{i === 0 ? '★' : i + 1}</span>

              <div className="airline-cell">
                <AirlineLogo airline={f.airline} logoUrl={f.airline_logo} />
                <div className="airline-info">
                  <div className="airline-name">{fmt(f.airline)}</div>
                  <div className="flight-num">{fmt(f.flight_number)}</div>
                </div>
              </div>

              <div className="time-block">
                <span className="time-val">{fmt(f.departure)}</span>
                <span className="time-label">Departs</span>
              </div>

              <div className="time-block">
                <span className="time-val">{fmt(f.arrival)}</span>
                <span className="time-label">Arrives</span>
              </div>

              <div className="duration-cell col-dur">
                <div className="dur-line">
                  <div className="dur-dot" />
                  <div className="dur-dash" />
                  <div className="dur-dot" />
                </div>
                <span className="dur-val">{fmt(f.duration)}</span>
                {via && <span className="via-tag">{via}</span>}
              </div>

              <div className="stops-cell">{stopChip(f.stops)}</div>

              <div className="price-cell">
                <div className="price-val">{fmt(f.price)}</div>
                <div className="price-sub">{fmt(f.cabin_class)}</div>
              </div>

              <div className="status-cell">{statusChip(f.live_status)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ─── Hotel Section ──────────────────────────────────────────────────────────── */
function HotelSection({ hotels, hotelSource }) {
  if (!hotels?.length) return null;
  const isLive = hotelSource === 'live';
  // ✅ Hotel source badge unchanged — Makcorps live data is a different concept
  const noteEl = isLive
    ? <span className="data-badge sched-badge">🟢 Live</span>
    : <span className="data-badge est-badge">⚪ Estimated</span>;

  return (
    <div className="section" style={{marginBottom:12}}>
      <div className="section-head">
        <div className="section-title"><span className="section-icon">🏨</span> Hotels</div>
        {noteEl}
      </div>
      <div className="hotel-header">
        <span className="col-head">#</span>
        <span className="col-head">Hotel</span>
        <span className="col-head h-cat">Category</span>
        <span className="col-head">Price / Night</span>
        <span className="col-head">Rating</span>
        <span className="col-head h-src">Source</span>
      </div>
      <div className="hotels-grid">
        {hotels.map((h, i) => (
          <div key={i} className={`hotel-card ${i === 0 ? 'best' : ''}`}>
            <span className={`rank ${i === 0 ? 'r1' : ''}`}>{i === 0 ? '★' : i + 1}</span>
            <div className="hotel-info">
              <div className="hotel-name">{fmt(h.name)}</div>
              {h.amenities && <div className="hotel-src" style={{fontSize:11.5,color:'var(--muted)',marginTop:2}}>{h.amenities.slice(0,60)}{h.amenities.length>60?'…':''}</div>}
            </div>
            <div className="h-cat">{catChip(h.category)}</div>
            <div>{priceTag(h.price_per_night)}</div>
            <div>{starsEl(h.rating)}</div>
            <div className="h-src" style={{fontSize:11,color:'var(--muted)'}}>{fmt(h.source)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Activity Section ────────────────────────────────────────────────────────── */
function ActivitySection({ activities }) {
  if (!activities?.length) return null;
  return (
    <div className="section" style={{marginBottom:12}}>
      <div className="section-head">
        <div className="section-title"><span className="section-icon">🎯</span> Activities & Tours</div>
      </div>
      <div className="act-header">
        <span className="col-head">#</span>
        <span className="col-head">Activity</span>
        <span className="col-head">Price</span>
        <span className="col-head a-dur">Duration</span>
      </div>
      <div className="activities-list">
        {activities.map((a, i) => (
          <div key={i} className="activity-card">
            <span className="rank">{i + 1}</span>
            <div>
              <div className="activity-name">{fmt(a.name)}</div>
              <div className="activity-desc">{fmt(a.description)}</div>
            </div>
            <div>{priceTag(a.price)}</div>
            <div className="a-dur" style={{fontSize:12.5,color:'var(--muted)'}}>{fmt(a.duration)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Budget Card ─────────────────────────────────────────────────────────────── */
function BudgetCard({ budget }) {
  if (!budget) return null;
  return (
    <div className="budget-section" style={{marginBottom:12}}>
      <div className="section-head">
        <div className="section-title"><span className="section-icon">💰</span> Cost Breakdown</div>
        <span className={`budget-badge ${budget.fits ? 'fits' : 'over'}`}>
          {budget.fits ? '✅ Within budget' : '⚠️ Over budget'}
        </span>
      </div>
      <div className="budget-rows">
        <div className="budget-row">
          <span className="b-label">Cheapest Flight</span>
          <span className="b-val">{budget.cheapest_flight}</span>
        </div>
        <div className="budget-row">
          <span className="b-label">Hotel Total</span>
          <span className="b-val">{budget.hotel_total}</span>
        </div>
        <div className="budget-row">
          <span className="b-label">Activities (est.)</span>
          <span className="b-val">{budget.activities_estimate}</span>
        </div>
        <div className="budget-divider" />
        <div className={`budget-row budget-total ${budget.fits ? 'fits' : 'over'}`}>
          <span className="b-label">Estimated Total</span>
          <span className="b-val">{budget.total_estimate}</span>
        </div>
        {budget.budget && (
          <div className="budget-row" style={{opacity:.6}}>
            <span className="b-label">Your Budget</span>
            <span className="b-val">{budget.budget}</span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Recommendation Card ─────────────────────────────────────────────────────── */
function RecCard({ text }) {
  if (!text) return null;
  return (
    <div className="rec-card">
      <div className="rec-title">✨ AI Travel Recommendation</div>
      <div className="rec-body">{text}</div>
    </div>
  );
}

/* ─── Rich Bot Message ────────────────────────────────────────────────────────── */
function BotMessage({ text, sd, isLoading }) {
  if (isLoading) return (
    <div className="bubble plain"><div className="typing"><span/><span/><span/></div></div>
  );
  if (!sd) return <div className="bubble plain">{text}</div>;

  const { trip, flights, hotels, activities, recommendation, flight_note, hotel_source, budget_summary } = sd;
  return (
    <div className="bubble rich">
      {text && <div className="bubble plain" style={{marginBottom:12}}>{text}</div>}
      <TripHeader trip={trip} />
      <FlightSection flights={flights} note={flight_note} />
      <HotelSection hotels={hotels} hotelSource={hotel_source} />
      <ActivitySection activities={activities} />
      <BudgetCard budget={budget_summary} />
      <RecCard text={recommendation} />
    </div>
  );
}

/* ─── Main App ────────────────────────────────────────────────────────────────── */
export default function App() {
  const [messages, setMessages]  = useState([]);
  const [input, setInput]        = useState('');
  const [loading, setLoading]    = useState(false);
  const [threadId, setThreadId]  = useState(null);
  const [suggestions, setSugg]   = useState([]);
  const pollerRef = useRef(null);
  const endRef    = useRef(null);
  const taRef     = useRef(null);

  useEffect(() => {
    setMessages([{ type:'bot', text:"Hi! I'm your AI travel assistant ✈️\nAsk me about flights, hotels, or a full trip plan!", sd:null }]);
    setSugg([
      'Flights from Mumbai to Paris, June 20 ✈️',
      'Plan 5-day Bali trip from Delhi 🗺️',
      'Hotels in Singapore for 3 nights 🏨',
      'Best places to visit in Tokyo 🗼',
    ]);
    setThreadId(`sess_${Date.now()}`);
    return () => clearInterval(pollerRef.current);
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior:'smooth' }); }, [messages]);

  const poll = (taskId) => {
    pollerRef.current = setInterval(async () => {
      try {
        const res = await axios.get(`http://localhost:8000/chat/status/${taskId}`);
        const { status, result } = res.data;
        if (status === 'completed' || status === 'failed') {
          clearInterval(pollerRef.current);
          setLoading(false);
          setMessages(prev => [
            ...prev.slice(0,-1),
            {
              type:'bot',
              text: status==='completed' ? result.reply : 'Something went wrong. Please try again.',
              sd: status==='completed' ? (result.structured_data || null) : null,
            },
          ]);
          setSugg([]);
        }
      } catch { clearInterval(pollerRef.current); setLoading(false); }
    }, 2000);
  };

  const send = async (txt = input) => {
    if (!txt.trim() || loading) return;
    setMessages(prev => [
      ...prev,
      { type:'user', text:txt },
      { type:'bot', text:'', sd:null, isLoading:true },
    ]);
    setInput(''); setLoading(true); setSugg([]);
    if (taRef.current) taRef.current.style.height = 'auto';
    try {
      const res = await axios.post('http://localhost:8000/chat', {
        message:txt, thread_id:threadId, is_continuation:true,
      });
      poll(res.data.task_id);
    } catch {
      setLoading(false);
      setMessages(prev => [...prev.slice(0,-1),
        { type:'bot', text:'Could not reach the server. Is it running?', sd:null }]);
    }
  };

  return (
    <>
      <FontInjector />
      <style>{STYLES}</style>
      <div className="app">
        {/* Header */}
        <header className="app-header">
          <div className="header-brand">
            <span className="brand-icon">✈️</span>
            <span className="brand-name">Tripy AI</span>
            <span className="brand-tag">Travel Planner</span>
          </div>
          {/* ✅ Changed "Live Flights" → "Estimated Flights" */}
          <div className="header-pills">
            <span className="pill">Estimated Flights</span>
            <span className="pill">Hotels</span>
            <span className="pill">Activities</span>
          </div>
        </header>

        {/* Messages */}
        <div className="chat-area">
          {messages.map((msg, i) => (
            <div key={i} className={`msg-row ${msg.type}`}>
              {msg.type === 'bot' && <div className="avatar">🤖</div>}
              {msg.type === 'bot'
                ? <BotMessage text={msg.text} sd={msg.sd} isLoading={msg.isLoading} />
                : <div className="bubble user">{msg.text}</div>
              }
            </div>
          ))}
          <div ref={endRef} />
        </div>

        {/* Suggestions */}
        {suggestions.length > 0 && (
          <div className="suggestions">
            {suggestions.map((s,i) => (
              <button key={i} className="sug-btn" onClick={() => send(s)}>{s}</button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="input-wrap">
          <div className="input-inner">
            <textarea
              ref={taRef}
              className="chat-input"
              value={input}
              disabled={loading}
              placeholder="e.g. Plan a 5-day trip from Delhi to Singapore, June 15th, 2 adults, budget $4000"
              onChange={e => {
                setInput(e.target.value);
                e.target.style.height='auto';
                e.target.style.height=Math.min(e.target.scrollHeight,110)+'px';
              }}
              onKeyDown={e => {
                if (e.key==='Enter' && !e.shiftKey && !loading) { e.preventDefault(); send(); }
              }}
            />
            <button className="send-btn" disabled={loading || !input.trim()} onClick={() => send()}>
              {loading ? '…' : '↑'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
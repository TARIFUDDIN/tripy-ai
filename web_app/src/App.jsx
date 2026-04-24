/**
 * App.jsx — Tripy AI · Dashboard + Full-Screen Chat
 * FIXES applied:
 *   1. BookingDetailPage moved OUT of App() to top-level component
 *   2. React Router (BrowserRouter + Routes) added
 *   3. /booking/:bookingId route wired up
 *   4. Sidebar nav uses useNavigate() instead of raw tab state for deep-links to work
 */

import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import {
  BrowserRouter,
  Routes,
  Route,
  useNavigate,
  useParams,
  useLocation,
} from 'react-router-dom';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const FontLoader = () => {
  useEffect(() => {
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = 'https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300&family=IBM+Plex+Mono:wght@400;500&display=swap';
    document.head.appendChild(l);
  }, []);
  return null;
};

const CSS = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #0a0d12;
    --surface:   #111520;
    --surface2:  #161b28;
    --bg3:       #1a2035;
    --border:    rgba(255,255,255,0.07);
    --border2:   rgba(255,255,255,0.13);
    --accent:    #4f8ef7;
    --accent2:   #7c5cfc;
    --gold:      #f0c040;
    --green:     #34d399;
    --red:       #f87171;
    --muted:     rgba(255,255,255,0.35);
    --text:      #e8edf5;
    --text2:     rgba(232,237,245,0.7);
    --font-h:    'Syne', sans-serif;
    --font-b:    'DM Sans', sans-serif;
    --font-m:    'IBM Plex Mono', monospace;
    --r:         12px;
    --r-sm:      8px;
    --sidebar:   220px;
  }

  html, body, #root {
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-b);
    font-size: 14px;
    line-height: 1.6;
    overflow: hidden;
  }

  .shell { display: flex; height: 100vh; overflow: hidden; }

  /* ══ SIDEBAR ══ */
  .sidebar {
    position: fixed; left: 0; top: 0; bottom: 0;
    width: var(--sidebar);
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex; flex-direction: column;
    z-index: 50;
  }
  .sidebar-logo {
    display: flex; align-items: center; gap: 9px;
    padding: 20px 18px 16px;
    border-bottom: 1px solid var(--border);
  }
  .logo-icon {
    width: 32px; height: 32px; border-radius: 8px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    display: flex; align-items: center; justify-content: center; font-size: 16px;
  }
  .logo-name {
    font-family: var(--font-h); font-weight: 800; font-size: 16px;
    background: linear-gradient(135deg, #4f8ef7, #7c5cfc);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }
  .logo-ver { font-size: 10px; color: var(--muted); margin-left: auto; }

  .nav-section { padding: 14px 10px 4px; flex: 1; }
  .nav-label { font-size: 10px; color: var(--muted); letter-spacing:.7px; text-transform:uppercase; padding: 0 8px 6px; }
  .nav-item {
    display: flex; align-items: center; gap: 9px;
    padding: 10px; border-radius: var(--r-sm);
    font-size: 13.5px; color: var(--text2); cursor: pointer;
    transition: all .15s; border: 1px solid transparent; margin-bottom: 2px;
    user-select: none;
  }
  .nav-item:hover { background: rgba(255,255,255,0.05); color: var(--text); }
  .nav-item.active { background: rgba(79,142,247,0.12); color: var(--accent); border-color: rgba(79,142,247,0.25); }
  .nav-icon { font-size: 15px; width: 18px; text-align: center; flex-shrink: 0; }

  .sidebar-footer {
    padding: 12px 10px 18px;
    border-top: 1px solid var(--border);
  }
  .ai-btn {
    display: flex; align-items: center; gap: 8px;
    width: 100%; padding: 11px 14px; border-radius: var(--r-sm);
    background: linear-gradient(135deg, rgba(79,142,247,0.15), rgba(124,92,252,0.15));
    border: 1px solid rgba(79,142,247,0.3); color: var(--accent);
    font-size: 13px; font-weight: 600; cursor: pointer; transition: all .15s;
    font-family: var(--font-b);
  }
  .ai-btn:hover, .ai-btn.active {
    background: linear-gradient(135deg, rgba(79,142,247,0.3), rgba(124,92,252,0.25));
    border-color: rgba(79,142,247,0.6);
    box-shadow: 0 0 20px rgba(79,142,247,0.2);
  }
  .pulse-dot {
    width: 7px; height: 7px; border-radius: 50%; background: var(--green);
    margin-left: auto; animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(.8)} }

  /* ══ MAIN AREA ══ */
  .main {
    flex: 1; margin-left: var(--sidebar);
    overflow-y: auto; overflow-x: hidden;
    scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.07) transparent;
    min-width: 0;
  }
  .main::-webkit-scrollbar { width: 4px; }
  .main::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 4px; }

  .page-header { display: flex; align-items: center; justify-content: space-between; padding: 24px 28px 0; }
  .page-title { font-family: var(--font-h); font-size: 22px; font-weight: 800; letter-spacing: -.3px; }
  .page-sub { font-size: 13px; color: var(--muted); margin-top: 2px; }

  .stats-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; padding: 20px 28px 0; }
  .stat-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--r); padding: 16px 18px; position: relative; overflow: hidden;
  }
  .stat-card::before {
    content:''; position:absolute; inset:0;
    background: radial-gradient(ellipse at 80% 20%, var(--accent-glow,rgba(79,142,247,0.06)) 0%, transparent 70%);
    pointer-events:none;
  }
  .stat-label { font-size: 11px; color: var(--muted); letter-spacing:.4px; text-transform:uppercase; }
  .stat-val { font-family: var(--font-h); font-size: 26px; font-weight: 800; margin: 4px 0 6px; }
  .stat-delta { font-size: 11.5px; display:flex; align-items:center; gap:4px; }
  .delta-up { color: var(--green); }
  .delta-down { color: var(--red); }

  .dash-section { margin: 20px 28px 0; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); overflow: hidden; }
  .dash-section-head {
    display:flex; align-items:center; justify-content:space-between;
    padding: 14px 18px; border-bottom: 1px solid var(--border);
    background: rgba(0,0,0,0.15);
  }
  .dash-section-title { font-family: var(--font-h); font-size: 14px; font-weight: 700; display:flex; align-items:center; gap:7px; }

  .bookings-table { width:100%; border-collapse:collapse; }
  .bookings-table th { padding:10px 18px; text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:var(--muted); background:rgba(0,0,0,0.15); font-weight:600; }
  .bookings-table td { padding:13px 18px; border-top:1px solid var(--border); font-size:13px; vertical-align:middle; }
  .bookings-table tr:hover td { background:rgba(255,255,255,0.02); }
  .route-cell { display:flex; align-items:center; gap:6px; font-weight:500; }
  .route-arrow { color:var(--muted); }
  .source-badge { font-size:10px; font-weight:600; padding:2px 8px; border-radius:20px; }
  .src-pdf  { background:rgba(79,142,247,0.1); color:var(--accent); border:1px solid rgba(79,142,247,0.25); }
  .src-chat { background:rgba(240,192,64,0.1);  color:var(--gold);  border:1px solid rgba(240,192,64,0.25); }
  .pnr-code { font-family:var(--font-m); font-size:12px; color:var(--accent); }
  .empty-row td { text-align:center; color:var(--muted); padding:32px; }

  /* Upload page */
  .upload-zone {
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    padding: 40px 20px; gap:12px;
    border: 1.5px dashed rgba(79,142,247,0.35); border-radius: var(--r);
    background: rgba(79,142,247,0.03); margin: 20px 28px;
    transition: all .2s; cursor:pointer; text-align:center;
  }
  .upload-zone:hover { border-color: rgba(79,142,247,0.6); background: rgba(79,142,247,0.07); }
  .upload-zone.drag  { border-color: var(--accent); background: rgba(79,142,247,0.1); }
  .upload-icon { font-size: 36px; }
  .upload-title { font-family: var(--font-h); font-size: 16px; font-weight: 700; }
  .upload-sub { font-size: 13px; color: var(--muted); }
  .upload-btn {
    padding: 8px 22px; border-radius: 20px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    border: none; color: #fff; font-size: 13px; font-weight: 600;
    cursor:pointer; font-family: var(--font-b); transition: opacity .15s;
  }
  .upload-btn:hover { opacity:.88; }
  .upload-btn:disabled { opacity:.4; cursor:default; }

  .ticket-result {
    margin: 0 28px 20px;
    background: var(--surface); border: 1px solid var(--border2);
    border-radius: var(--r); overflow: hidden;
    animation: slideIn .3s ease;
  }
  @keyframes slideIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
  .ticket-banner {
    padding: 14px 18px; display:flex; align-items:center; gap:10px;
    background: linear-gradient(135deg, rgba(52,211,153,0.08), rgba(79,142,247,0.08));
    border-bottom: 1px solid var(--border);
  }
  .ticket-banner .conf-badge { margin-left:auto; font-size:11px; font-weight:600; padding:3px 10px; border-radius:20px; }
  .conf-high { background:rgba(52,211,153,0.12); color:var(--green); border:1px solid rgba(52,211,153,0.3); }
  .conf-med  { background:rgba(240,192,64,0.12);  color:var(--gold);  border:1px solid rgba(240,192,64,0.3); }
  .conf-low  { background:rgba(248,113,113,0.12); color:var(--red);   border:1px solid rgba(248,113,113,0.3); }
  .ticket-fields { display:grid; grid-template-columns:repeat(3,1fr); }
  .ticket-field { padding:14px 18px; border-right:1px solid var(--border); border-bottom:1px solid var(--border); }
  .ticket-field:nth-child(3n) { border-right:none; }
  .ticket-field:nth-last-child(-n+3) { border-bottom:none; }
  .tf-label { font-size:10.5px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; margin-bottom:4px; }
  .tf-val { font-size:14px; font-weight:500; }
  .tf-val.mono { font-family:var(--font-m); font-size:13px; color:var(--accent); }
  .tf-empty { color:var(--muted); font-style:italic; font-size:12px; }

  .addons-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; padding:16px 18px; }
  .addon-card {
    border:1px solid var(--border); border-radius:var(--r-sm);
    padding:14px; cursor:pointer; transition:all .15s;
    background:var(--bg3); position:relative;
  }
  .addon-card:hover { border-color:rgba(79,142,247,0.4); background:rgba(79,142,247,0.06); }
  .addon-card.selected { border-color:var(--accent); background:rgba(79,142,247,0.1); }
  .addon-card .popular-tag {
    position:absolute; top:-1px; right:10px;
    background:var(--accent); color:#fff;
    font-size:9px; font-weight:700; padding:2px 8px; border-radius:0 0 6px 6px;
  }
  .addon-icon { font-size:20px; margin-bottom:8px; }
  .addon-name { font-weight:600; font-size:13px; margin-bottom:3px; }
  .addon-desc { font-size:11.5px; color:var(--muted); margin-bottom:10px; line-height:1.4; }
  .addon-footer { display:flex; align-items:center; justify-content:space-between; }
  .addon-price { font-family:var(--font-h); font-size:15px; font-weight:700; }
  .addon-comm { font-size:10.5px; color:var(--green); font-weight:600; }
  .check-ring {
    width:18px; height:18px; border-radius:50%;
    border:1.5px solid var(--border2); flex-shrink:0;
    display:flex; align-items:center; justify-content:center; transition:all .15s;
  }
  .addon-card.selected .check-ring { background:var(--accent); border-color:var(--accent); }
  .commission-bar {
    margin:0 18px 16px; padding:12px 16px; border-radius:var(--r-sm);
    background:linear-gradient(135deg,rgba(52,211,153,0.08),rgba(79,142,247,0.06));
    border:1px solid rgba(52,211,153,0.2);
    display:flex; align-items:center; justify-content:space-between;
  }
  .comm-earn { font-family:var(--font-h); font-size:18px; font-weight:700; color:var(--green); }
  .page-bottom { height:32px; }

  /* ══ FULL-SCREEN CHAT ══ */
  .chat-full {
    display: flex; flex-direction: column; height: 100vh;
    background: var(--bg);
  }
  .chat-topbar {
    display: flex; align-items: center; gap: 12px;
    padding: 14px 24px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .chat-topbar-icon {
    width: 38px; height: 38px; border-radius: 10px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    display: flex; align-items: center; justify-content: center; font-size: 18px;
  }
  .chat-topbar-title { font-family: var(--font-h); font-size: 16px; font-weight: 700; }
  .chat-topbar-sub { font-size: 12px; color: var(--muted); }
  .chat-topbar-pills { margin-left: auto; display: flex; gap: 8px; }
  .topbar-pill {
    padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 500;
    border: 1px solid var(--border2); background: rgba(255,255,255,0.04); color: var(--muted);
  }
  .chat-messages-area {
    flex: 1; overflow-y: auto; padding: 24px 0 8px;
    scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent;
  }
  .chat-messages-area::-webkit-scrollbar { width: 5px; }
  .chat-messages-area::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
  .msg-row { display: flex; gap: 12px; padding: 6px 24px; animation: fadeUp .3s ease both; }
  .msg-row.user { flex-direction: row-reverse; }
  @keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
  .avatar {
    width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center; font-size: 17px;
    margin-top: 2px;
    background: linear-gradient(135deg, #1e2a45, #2a1e45);
    border: 1px solid var(--border2);
  }
  .bubble-user {
    max-width: 640px; border-radius: 14px; font-size: 14.5px; line-height: 1.65;
    background: linear-gradient(135deg, #1b2d55, #22194a);
    border: 1px solid rgba(79,142,247,0.25); padding: 12px 18px; color: var(--text);
  }
  .bubble-plain {
    max-width: 760px; border-radius: 14px; font-size: 14.5px; line-height: 1.65;
    background: var(--surface); border: 1px solid var(--border);
    padding: 14px 18px; color: var(--text2);
  }
  .bubble-rich { width: 100%; }
  .typing { display:flex; gap:5px; padding:16px 18px; background:var(--surface); border-radius:14px; border:1px solid var(--border); width: fit-content; }
  .typing span { width:7px; height:7px; border-radius:50%; background:var(--accent); opacity:.3; animation:blink 1.2s infinite; }
  .typing span:nth-child(2){animation-delay:.2s}
  .typing span:nth-child(3){animation-delay:.4s}
  @keyframes blink{0%,80%,100%{opacity:.3}40%{opacity:1}}
  .suggestions { padding: 8px 24px 0; display: flex; gap: 8px; flex-wrap: wrap; }
  .sug-btn {
    padding: 8px 16px; border-radius: 20px; font-size: 13px; font-weight: 500;
    background: rgba(255,255,255,0.04); border: 1px solid var(--border2);
    color: var(--text2); cursor: pointer; transition: all .15s; font-family: var(--font-b);
  }
  .sug-btn:hover { background: rgba(79,142,247,0.1); border-color: rgba(79,142,247,0.35); color: var(--text); transform: translateY(-1px); }
  .chat-input-wrap { flex-shrink: 0; padding: 12px 24px 18px; border-top: 1px solid var(--border); background: var(--surface); }
  .chat-input-inner {
    display: flex; gap: 10px; align-items: flex-end;
    background: var(--surface2); border: 1.5px solid var(--border2);
    border-radius: 16px; padding: 10px 12px 10px 18px;
    transition: border-color .15s, box-shadow .15s;
  }
  .chat-input-inner:focus-within { border-color: rgba(79,142,247,0.5); box-shadow: 0 0 0 3px rgba(79,142,247,0.08); }
  .chat-textarea {
    flex: 1; resize: none; background: transparent; border: none; outline: none;
    color: var(--text); font-family: var(--font-b); font-size: 14.5px;
    line-height: 1.55; min-height: 22px; max-height: 110px;
  }
  .chat-textarea::placeholder { color: var(--muted); }
  .send-btn {
    width: 38px; height: 38px; border-radius: 10px; border: none; cursor: pointer;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    color: #fff; font-size: 17px; display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; transition: opacity .15s, transform .1s;
    box-shadow: 0 2px 10px rgba(79,142,247,0.35);
  }
  .send-btn:hover:not(:disabled) { opacity:.88; transform:scale(1.06); }
  .send-btn:disabled { opacity:.3; cursor:default; box-shadow:none; }

  /* ══ RICH CHAT COMPONENTS ══ */
  .trip-card {
    background: linear-gradient(135deg, #0f1928, #14102a);
    border: 1px solid var(--border2); border-radius: var(--r);
    padding: 18px 22px; margin-bottom: 12px;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
    position: relative; overflow: hidden;
  }
  .trip-card::before {
    content:''; position:absolute; inset:0;
    background: radial-gradient(ellipse at 30% 50%, rgba(79,142,247,0.07) 0%, transparent 70%);
    pointer-events: none;
  }
  .trip-route { display: flex; align-items: center; gap: 10px; }
  .trip-city { font-family: var(--font-h); font-size: 22px; font-weight: 800; letter-spacing:-.5px; }
  .trip-origin { color: #7ab3ff; }
  .trip-dest   { color: #c49fff; }
  .trip-arrow  { color: var(--muted); font-size: 18px; }
  .trip-meta   { display: flex; gap: 18px; flex-wrap: wrap; }
  .meta-item   { display: flex; flex-direction: column; gap: 2px; }
  .meta-label  { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .6px; }
  .meta-val    { font-size: 14px; font-weight: 500; }
  .rich-section { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); margin-bottom: 12px; overflow: hidden; }
  .rich-section-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 18px; border-bottom: 1px solid var(--border);
    background: rgba(0,0,0,0.2);
  }
  .rich-section-title { font-family: var(--font-h); font-size: 14px; font-weight: 700; display: flex; align-items: center; gap: 7px; }
  .data-badge { font-size: 10.5px; font-weight: 600; padding: 3px 10px; border-radius: 20px; letter-spacing: .4px; text-transform: uppercase; }
  .badge-est   { background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid var(--border); }
  .badge-sched { background: rgba(79,142,247,0.12); color: var(--accent); border: 1px solid rgba(79,142,247,0.3); }
  .badge-live  { background: rgba(52,211,153,0.1);  color: var(--green); border: 1px solid rgba(52,211,153,0.3); }
  .flight-table-head, .flight-table-row {
    display: grid;
    grid-template-columns: 28px 200px 1fr 1fr 100px 80px 110px 90px;
    align-items: center; gap: 12px; padding: 10px 18px; font-size: 13px;
  }
  .flight-table-head { border-bottom: 1px solid var(--border); background: rgba(0,0,0,0.2); }
  .flight-table-row { border-bottom: 1px solid var(--border); transition: background .12s; cursor: default; }
  .flight-table-row:last-child { border-bottom: none; }
  .flight-table-row:hover { background: rgba(255,255,255,0.025); }
  .flight-table-row.best { background: rgba(79,142,247,0.06); }
  .flight-table-row.best:hover { background: rgba(79,142,247,0.09); }
  .col-h { font-size: 10.5px; text-transform: uppercase; letter-spacing: .6px; color: var(--muted); font-weight: 600; }
  .col-r { text-align: right; }
  .col-c { text-align: center; }
  .rank { font-size: 14px; font-weight: 700; color: var(--muted); }
  .rank.gold { color: var(--gold); }
  .airline-cell { display: flex; align-items: center; gap: 9px; min-width: 0; }
  .airline-logo {
    width: 34px; height: 34px; border-radius: 8px; flex-shrink: 0;
    background: rgba(255,255,255,0.06); border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center; overflow: hidden;
  }
  .airline-logo img { width: 26px; height: 26px; object-fit: contain; }
  .airline-initials { font-size: 10px; font-weight: 700; color: var(--accent); }
  .airline-name { font-weight: 600; font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .flight-num  { font-size: 11px; color: var(--muted); font-family: var(--font-m); }
  .time-val   { font-size: 15px; font-weight: 600; }
  .time-label { font-size: 10px; color: var(--muted); }
  .dur-cell { display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .dur-line { display: flex; align-items: center; gap: 6px; width: 100%; }
  .dur-dot  { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
  .dur-dash { flex: 1; height: 1px; background: var(--border2); }
  .dur-val  { font-size: 12px; color: var(--text2); font-weight: 500; white-space: nowrap; }
  .stop-chip { display: inline-block; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 20px; }
  .nonstop  { background: rgba(52,211,153,0.12); color: var(--green); border: 1px solid rgba(52,211,153,0.25); }
  .one-stop { background: rgba(240,192,64,0.1);  color: var(--gold);  border: 1px solid rgba(240,192,64,0.25); }
  .multi    { background: rgba(248,113,113,0.1); color: var(--red);   border: 1px solid rgba(248,113,113,0.25); }
  .price-val { font-size: 17px; font-weight: 700; text-align: right; }
  .price-sub { font-size: 10.5px; color: var(--muted); text-align: right; }
  .status-chip { font-size: 9.5px; font-weight: 700; padding: 3px 8px; border-radius: 20px; letter-spacing: .5px; text-transform: uppercase; }
  .chip-est   { background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid var(--border); }
  .chip-sched { background: rgba(79,142,247,0.1); color: var(--accent); border: 1px solid rgba(79,142,247,0.3); }
  .hotel-table-head, .hotel-table-row {
    display: grid;
    grid-template-columns: 28px 1fr 90px 140px 110px 80px;
    align-items: center; gap: 12px; padding: 10px 18px; font-size: 13px;
  }
  .hotel-table-head { border-bottom: 1px solid var(--border); background: rgba(0,0,0,0.2); }
  .hotel-table-row  { border-bottom: 1px solid var(--border); transition: background .12s; }
  .hotel-table-row:last-child { border-bottom: none; }
  .hotel-table-row:hover { background: rgba(255,255,255,0.025); }
  .hotel-table-row.best { background: rgba(79,142,247,0.06); }
  .hotel-name { font-weight: 600; font-size: 13.5px; }
  .hotel-amenities { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .cat-chip { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 20px; }
  .cat-s2 { background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid var(--border); }
  .cat-s3 { background: rgba(79,142,247,0.1); color: #8ab8ff; border: 1px solid rgba(79,142,247,0.25); }
  .cat-s4 { background: rgba(124,92,252,0.1); color: #b39bff; border: 1px solid rgba(124,92,252,0.25); }
  .cat-s5 { background: rgba(240,192,64,0.1); color: var(--gold); border: 1px solid rgba(240,192,64,0.25); }
  .stars-row { display: flex; align-items: center; gap: 3px; }
  .star-f { color: var(--gold); font-size: 12px; }
  .star-e { color: rgba(255,255,255,0.15); font-size: 12px; }
  .rating-num { font-size: 11.5px; color: var(--text2); margin-left: 3px; font-weight: 500; }
  .act-table-head, .act-table-row {
    display: grid;
    grid-template-columns: 28px 1fr 100px 90px;
    align-items: start; gap: 12px; padding: 10px 18px; font-size: 13px;
  }
  .act-table-head { border-bottom: 1px solid var(--border); background: rgba(0,0,0,0.2); }
  .act-table-row  { border-bottom: 1px solid var(--border); transition: background .12s; }
  .act-table-row:last-child { border-bottom: none; }
  .act-table-row:hover { background: rgba(255,255,255,0.02); }
  .act-name { font-weight: 600; font-size: 13.5px; }
  .act-desc { font-size: 11.5px; color: var(--muted); margin-top: 3px; line-height: 1.5; }
  .price-free { color: var(--green); font-weight: 700; font-size: 13px; }
  .price-paid { font-weight: 700; font-size: 13px; }
  .budget-section { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); margin-bottom: 12px; overflow: hidden; }
  .budget-rows { padding: 16px 20px; display: flex; flex-direction: column; gap: 10px; }
  .budget-row { display: flex; align-items: center; justify-content: space-between; font-size: 14px; }
  .budget-row .b-label { color: var(--text2); }
  .budget-row .b-val   { font-weight: 600; }
  .budget-divider { height: 1px; background: var(--border); margin: 4px 0; }
  .budget-total .b-label { font-weight: 700; color: var(--text); font-size: 15px; }
  .budget-total .b-val   { font-size: 18px; font-weight: 700; }
  .budget-total.fits .b-val { color: var(--green); }
  .budget-total.over .b-val { color: var(--red); }
  .budget-badge { padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; }
  .budget-fits { background: rgba(52,211,153,0.12); color: var(--green); border: 1px solid rgba(52,211,153,0.3); }
  .budget-over { background: rgba(248,113,113,0.1); color: var(--red); border: 1px solid rgba(248,113,113,0.3); }
  .rec-card {
    background: linear-gradient(135deg, #0d1b30, #130d28);
    border: 1px solid rgba(79,142,247,0.2); border-radius: var(--r);
    padding: 18px 22px; margin-bottom: 12px;
  }
  .rec-title { font-family: var(--font-h); font-size: 14px; font-weight: 700; color: var(--accent); margin-bottom: 9px; display: flex; align-items: center; gap: 7px; }
  .rec-body  { font-size: 14px; color: var(--text2); line-height: 1.75; }
  .spinner { width:14px; height:14px; border:2px solid rgba(79,142,247,.2); border-top-color:var(--accent); border-radius:50%; animation:spin .7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  @media (max-width: 900px) {
    .stats-grid { grid-template-columns: repeat(2,1fr); }
    .addons-grid { grid-template-columns: repeat(2,1fr); }
    :root { --sidebar: 180px; }
    .flight-table-head, .flight-table-row { grid-template-columns: 20px 1fr 80px 80px 80px; }
    .hotel-table-head, .hotel-table-row { grid-template-columns: 20px 1fr 110px 90px; }
  }
`;

/* ─── Helpers ─── */
const fmt = v => (v === null || v === undefined || v === '—' ? '—' : v);

function StarsEl({ rating }) {
  if (!rating) return <span style={{color:'var(--muted)'}}>—</span>;
  const full  = Math.floor(rating);
  const empty = Math.max(0, 5 - full);
  return (
    <div className="stars-row">
      {'★'.repeat(full).split('').map((_,i) => <span key={i} className="star-f">★</span>)}
      {'☆'.repeat(empty).split('').map((_,i) => <span key={i} className="star-e">☆</span>)}
      <span className="rating-num">{rating}</span>
    </div>
  );
}

function CatChip({ cat }) {
  const s   = parseInt(cat) || 3;
  const cls = {2:'cat-s2',3:'cat-s3',4:'cat-s4',5:'cat-s5'}[Math.min(s,5)] || 'cat-s3';
  return <span className={`cat-chip ${cls}`}>{cat}</span>;
}

function StopChip({ stops }) {
  if (stops === 0 || stops === '0') return <span className="stop-chip nonstop">Non-stop</span>;
  if (stops === 1) return <span className="stop-chip one-stop">1 Stop</span>;
  return <span className="stop-chip multi">{stops} Stops</span>;
}

function StatusChip({ status }) {
  if (status === 'real_schedule') return <span className="status-chip chip-sched">SCHED</span>;
  return <span className="status-chip chip-est">EST</span>;
}

function AirlineLogo({ airline, logoUrl }) {
  const [err, setErr] = useState(false);
  const initials = (airline || '??').split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase();
  return (
    <div className="airline-logo">
      {logoUrl && !err
        ? <img src={logoUrl} alt={airline} onError={() => setErr(true)} />
        : <span className="airline-initials">{initials}</span>
      }
    </div>
  );
}

/* ─── Rich Sections ─── */
function TripHeader({ trip }) {
  if (!trip) return null;
  const dep = trip.departure_date
    ? new Date(trip.departure_date + 'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})
    : '—';
  const ret = trip.return_date
    ? new Date(trip.return_date + 'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short'})
    : null;
  return (
    <div className="trip-card">
      <div className="trip-route">
        <span className="trip-city trip-origin">{trip.origin || '?'}</span>
        <span className="trip-arrow">→</span>
        <span className="trip-city trip-dest">{trip.destination || '?'}</span>
      </div>
      <div className="trip-meta">
        <div className="meta-item">
          <span className="meta-label">Departs</span>
          <span className="meta-val">📅 {dep}{ret ? ` → ${ret}` : ''}</span>
        </div>
        {trip.adults && <div className="meta-item">
          <span className="meta-label">Travellers</span>
          <span className="meta-val">👤 {trip.adults} adult{trip.adults > 1 ? 's' : ''}</span>
        </div>}
        {trip.travel_class && <div className="meta-item">
          <span className="meta-label">Class</span>
          <span className="meta-val">💺 {trip.travel_class}</span>
        </div>}
      </div>
    </div>
  );
}

function FlightSection({ flights, note }) {
  if (!flights?.length) return null;
  const badge = note === 'real_schedule'
    ? <span className="data-badge badge-sched">🔵 Scheduled</span>
    : <span className="data-badge badge-est">⚪ Estimated</span>;
  return (
    <div className="rich-section">
      <div className="rich-section-head">
        <div className="rich-section-title">✈️ Flights</div>
        {badge}
      </div>
      <div className="flight-table-head">
        <span className="col-h">#</span>
        <span className="col-h">Airline</span>
        <span className="col-h">Departure</span>
        <span className="col-h">Arrival</span>
        <span className="col-h col-c">Duration</span>
        <span className="col-h col-c">Stops</span>
        <span className="col-h col-r">Price</span>
        <span className="col-h col-c">Status</span>
      </div>
      {flights.map((f, i) => (
        <div key={i} className={`flight-table-row ${i === 0 ? 'best' : ''}`}>
          <span className={`rank ${i === 0 ? 'gold' : ''}`}>{i === 0 ? '★' : i + 1}</span>
          <div className="airline-cell">
            <AirlineLogo airline={f.airline} logoUrl={f.airline_logo} />
            <div>
              <div className="airline-name">{fmt(f.airline)}</div>
              <div className="flight-num">{fmt(f.flight_number)}</div>
            </div>
          </div>
          <div>
            <div className="time-val">{fmt(f.departure)}</div>
            <div className="time-label">Departs</div>
          </div>
          <div>
            <div className="time-val">{fmt(f.arrival)}</div>
            <div className="time-label">Arrives</div>
          </div>
          <div className="dur-cell">
            <div className="dur-line"><div className="dur-dot"/><div className="dur-dash"/><div className="dur-dot"/></div>
            <span className="dur-val">{fmt(f.duration)}</span>
          </div>
          <div style={{textAlign:'center'}}><StopChip stops={f.stops}/></div>
          <div>
            <div className="price-val">{fmt(f.price)}</div>
            <div className="price-sub">{fmt(f.cabin_class)}</div>
          </div>
          <div style={{textAlign:'center'}}><StatusChip status={f.live_status}/></div>
        </div>
      ))}
    </div>
  );
}

function HotelSection({ hotels, hotelSource }) {
  if (!hotels?.length) return null;
  const badge = hotelSource === 'live'
    ? <span className="data-badge badge-live">🟢 Live</span>
    : <span className="data-badge badge-est">⚪ Estimated</span>;
  return (
    <div className="rich-section">
      <div className="rich-section-head">
        <div className="rich-section-title">🏨 Hotels</div>
        {badge}
      </div>
      <div className="hotel-table-head">
        <span className="col-h">#</span>
        <span className="col-h">Hotel</span>
        <span className="col-h">Category</span>
        <span className="col-h">Price / Night</span>
        <span className="col-h">Rating</span>
        <span className="col-h">Source</span>
      </div>
      {hotels.map((h, i) => (
        <div key={i} className={`hotel-table-row ${i === 0 ? 'best' : ''}`}>
          <span className={`rank ${i === 0 ? 'gold' : ''}`}>{i === 0 ? '★' : i + 1}</span>
          <div>
            <div className="hotel-name">{fmt(h.name)}</div>
            {h.amenities && <div className="hotel-amenities">{h.amenities.slice(0,60)}{h.amenities.length > 60 ? '…' : ''}</div>}
          </div>
          <CatChip cat={h.category}/>
          <div style={{fontWeight:600,fontSize:14}}>{fmt(h.price_per_night)}</div>
          <StarsEl rating={h.rating}/>
          <div style={{fontSize:11,color:'var(--muted)'}}>{fmt(h.source)}</div>
        </div>
      ))}
    </div>
  );
}

function ActivitySection({ activities }) {
  if (!activities?.length) return null;
  return (
    <div className="rich-section">
      <div className="rich-section-head">
        <div className="rich-section-title">🎯 Activities & Tours</div>
      </div>
      <div className="act-table-head">
        <span className="col-h">#</span>
        <span className="col-h">Activity</span>
        <span className="col-h">Price</span>
        <span className="col-h">Duration</span>
      </div>
      {activities.map((a, i) => (
        <div key={i} className="act-table-row">
          <span className="rank">{i + 1}</span>
          <div>
            <div className="act-name">{fmt(a.name)}</div>
            <div className="act-desc">{fmt(a.description)}</div>
          </div>
          <div>
            {(!a.price || a.price === '—' || a.price?.toLowerCase?.().includes('free'))
              ? <span className="price-free">Free</span>
              : <span className="price-paid">{a.price}</span>
            }
          </div>
          <div style={{fontSize:12,color:'var(--muted)'}}>{fmt(a.duration)}</div>
        </div>
      ))}
    </div>
  );
}

function BudgetCard({ budget }) {
  if (!budget) return null;
  return (
    <div className="budget-section">
      <div className="rich-section-head">
        <div className="rich-section-title">💰 Cost Breakdown</div>
      </div>
      <div className="budget-rows">
        <div className="budget-row"><span className="b-label">Cheapest Flight</span><span className="b-val">{budget.cheapest_flight}</span></div>
        <div className="budget-row"><span className="b-label">Hotel Total</span><span className="b-val">{budget.hotel_total}</span></div>
        <div className="budget-row"><span className="b-label">Activities (est.)</span><span className="b-val">{budget.activities_estimate}</span></div>
        <div className="budget-divider"/>
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

function RecCard({ text }) {
  if (!text) return null;
  return (
    <div className="rec-card">
      <div className="rec-title">✨ AI Travel Recommendation</div>
      <div className="rec-body">{text}</div>
    </div>
  );
}

/* ─── Bot Message renderer ─── */
function BotMessage({ text, sd, isLoading }) {
  if (isLoading) return (
    <div className="typing"><span/><span/><span/></div>
  );
  if (!sd) return <div className="bubble-plain">{text}</div>;
  const { trip, flights, hotels, activities, recommendation, flight_note, hotel_source, budget_summary } = sd;
  return (
    <div className="bubble-rich">
      {text && <div className="bubble-plain" style={{marginBottom:12}}>{text}</div>}
      <TripHeader trip={trip}/>
      <FlightSection flights={flights} note={flight_note}/>
      <HotelSection hotels={hotels} hotelSource={hotel_source}/>
      <ActivitySection activities={activities}/>
      <BudgetCard budget={budget_summary}/>
      <RecCard text={recommendation}/>
    </div>
  );
}

/* ─── Full-Screen Chat ─── */
function FullScreenChat() {
  const [msgs, setMsgs]       = useState([
    { type:'bot', text:"Hi! I'm your AI travel assistant ✈️\nAsk me about flights, hotels, or a full trip plan!", sd:null }
  ]);
  const [input, setInput]     = useState('');
  const [loading, setLoading] = useState(false);
  const [sugg, setSugg]       = useState([
    'Flights from Mumbai to Paris, June 20 ✈️',
    'Plan 5-day Bali trip from Delhi 🗺️',
    'Hotels in Singapore for 3 nights 🏨',
    'Best places to visit in Tokyo 🗼',
  ]);
  const [threadId]            = useState(`sess_${Date.now()}`);
  const pollerRef             = useRef();
  const endRef                = useRef();
  const taRef                 = useRef();

  useEffect(() => { endRef.current?.scrollIntoView({ behavior:'smooth' }); }, [msgs]);

  const poll = (taskId) => {
    pollerRef.current = setInterval(async () => {
      try {
        const r = await axios.get(`${API}/chat/status/${taskId}`);
        const { status, result } = r.data;
        if (status === 'completed' || status === 'failed') {
          clearInterval(pollerRef.current);
          setLoading(false);
          setMsgs(prev => [
            ...prev.slice(0, -1),
            {
              type: 'bot',
              text: status === 'completed' ? result.reply : 'Something went wrong. Please try again.',
              sd:   status === 'completed' ? (result.structured_data || null) : null,
            }
          ]);
          setSugg([]);
        }
      } catch { clearInterval(pollerRef.current); setLoading(false); }
    }, 2000);
  };

  const send = async (txt = input) => {
    if (!txt.trim() || loading) return;
    setMsgs(prev => [
      ...prev,
      { type:'user', text:txt },
      { type:'bot', text:'', sd:null, isLoading:true },
    ]);
    setInput(''); setLoading(true); setSugg([]);
    if (taRef.current) taRef.current.style.height = 'auto';
    try {
      const r = await axios.post(`${API}/chat`, { message:txt, thread_id:threadId, is_continuation:true });
      poll(r.data.task_id);
    } catch {
      setLoading(false);
      setMsgs(prev => [...prev.slice(0,-1), { type:'bot', text:'Could not reach server. Is it running?', sd:null }]);
    }
  };

  return (
    <div className="chat-full">
      <div className="chat-topbar">
        <div className="chat-topbar-icon">✈️</div>
        <div>
          <div className="chat-topbar-title">AI Travel Assistant</div>
          <div className="chat-topbar-sub">Flights · Hotels · Activities · Itineraries</div>
        </div>
        <div className="chat-topbar-pills">
          <span className="topbar-pill">Estimated Flights</span>
          <span className="topbar-pill">Hotels</span>
          <span className="topbar-pill">Activities</span>
        </div>
      </div>
      <div className="chat-messages-area">
        {msgs.map((msg, i) => (
          <div key={i} className={`msg-row ${msg.type}`}>
            {msg.type === 'bot' && <div className="avatar">🤖</div>}
            {msg.type === 'bot'
              ? <BotMessage text={msg.text} sd={msg.sd} isLoading={msg.isLoading}/>
              : <div className="bubble-user">{msg.text}</div>
            }
          </div>
        ))}
        <div ref={endRef}/>
      </div>
      {sugg.length > 0 && (
        <div className="suggestions">
          {sugg.map((s,i) => <button key={i} className="sug-btn" onClick={() => send(s)}>{s}</button>)}
        </div>
      )}
      <div className="chat-input-wrap">
        <div className="chat-input-inner">
          <textarea
            ref={taRef}
            className="chat-textarea"
            value={input}
            disabled={loading}
            placeholder="e.g. Plan a 5-day trip from Delhi to Singapore, June 15th, 2 adults, budget $4000"
            onChange={e => {
              setInput(e.target.value);
              e.target.style.height = 'auto';
              e.target.style.height = Math.min(e.target.scrollHeight, 110) + 'px';
            }}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !loading) { e.preventDefault(); send(); } }}
          />
          <button className="send-btn" disabled={loading || !input.trim()} onClick={() => send()}>
            {loading ? '…' : '↑'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Add-ons Section (shared by UploadPage + BookingDetailPage) ─── */
function AddonsSection({ bookingId }) {
  const [addons, setAddons]     = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [ordered, setOrdered]   = useState(null);
  const [loading, setLoading]   = useState(false);

  useEffect(() => { axios.get(`${API}/addons`).then(r => setAddons(r.data.addons)).catch(() => {}); }, []);

  const toggle = id => {
    if (ordered) return;
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  };
  const totalPrice = addons.filter(a => selected.has(a.id)).reduce((s,a) => s+a.price, 0);
  const totalComm  = addons.filter(a => selected.has(a.id)).reduce((s,a) => s+a.commission, 0);

  const confirm = async () => {
    if (!selected.size || !bookingId) return;
    setLoading(true);
    try { const r = await axios.post(`${API}/addons/select`, {booking_id:bookingId, addon_ids:[...selected]}); setOrdered(r.data); }
    catch {}
    setLoading(false);
  };

  if (!addons.length) return null;
  return (
    <div className="dash-section" style={{marginTop:20}}>
      <div className="dash-section-head">
        <div className="dash-section-title">🎁 Enhance your trip</div>
        {selected.size > 0 && !ordered && (
          <button onClick={confirm} disabled={loading} style={{padding:'6px 16px',borderRadius:20,background:'linear-gradient(135deg,#10b981,#059669)',border:'none',color:'#fff',fontSize:12,fontWeight:600,cursor:'pointer',fontFamily:'var(--font-b)',display:'flex',alignItems:'center',gap:6}}>
            {loading && <span className="spinner"/>}
            Confirm {selected.size} add-on{selected.size > 1 ? 's' : ''}
          </button>
        )}
      </div>
      {ordered ? (
        <div style={{padding:'20px 18px',textAlign:'center'}}>
          <div style={{fontSize:28,marginBottom:8}}>✅</div>
          <div style={{fontFamily:'var(--font-h)',fontSize:15,fontWeight:700,marginBottom:4}}>Add-ons confirmed!</div>
          <div style={{color:'var(--muted)',fontSize:13,marginBottom:12}}>Order #{ordered.order_id} · Total {ordered.total_price}</div>
          <div style={{display:'inline-flex',alignItems:'center',gap:8,background:'rgba(52,211,153,0.1)',border:'1px solid rgba(52,211,153,0.25)',borderRadius:20,padding:'6px 16px',color:'var(--green)',fontSize:13,fontWeight:600}}>
            💰 You earned {ordered.commission_earned} commission
          </div>
        </div>
      ) : (
        <>
          <div className="addons-grid">
            {addons.map(a => (
              <div key={a.id} className={`addon-card ${selected.has(a.id) ? 'selected' : ''}`} onClick={() => toggle(a.id)}>
                {a.popular && <div className="popular-tag">POPULAR</div>}
                <div className="addon-icon">{a.icon}</div>
                <div className="addon-name">{a.name}</div>
                <div className="addon-desc">{a.description}</div>
                <div className="addon-footer">
                  <div><div className="addon-price">${a.price}</div><div className="addon-comm">+${a.commission} commission</div></div>
                  <div className="check-ring">{selected.has(a.id) && <span style={{color:'#fff',fontSize:10}}>✓</span>}</div>
                </div>
              </div>
            ))}
          </div>
          {selected.size > 0 && (
            <div className="commission-bar">
              <div style={{fontSize:13,color:'var(--text2)'}}>{selected.size} add-on{selected.size > 1 ? 's' : ''} selected · Customer pays ${totalPrice}</div>
              <div>
                <div style={{fontSize:10.5,color:'var(--muted)',textAlign:'right',marginBottom:1}}>You earn</div>
                <div className="comm-earn">${totalComm}</div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ─── Dashboard ─── */
function StatCard({ label, value, delta, deltaUp, glow }) {
  return (
    <div className="stat-card" style={{'--accent-glow': glow || 'rgba(79,142,247,0.06)'}}>
      <div className="stat-label">{label}</div>
      <div className="stat-val">{value}</div>
      {delta && <div className={`stat-delta ${deltaUp ? 'delta-up' : 'delta-down'}`}>{deltaUp ? '↑' : '↓'} {delta}</div>}
    </div>
  );
}

function DashboardPage() {
  const [stats, setStats] = useState(null);
  useEffect(() => { axios.get(`${API}/dashboard/stats`).then(r => setStats(r.data)).catch(() => {}); }, []);
  return (
    <>
      <div className="page-header">
        <div><div className="page-title">Dashboard</div><div className="page-sub">Your booking and commission overview</div></div>
      </div>
      <div className="stats-grid">
        <StatCard label="Total bookings"    value={stats?.total_bookings ?? '—'} delta="this session" deltaUp/>
        <StatCard label="Revenue (add-ons)" value={stats?.total_revenue ?? '—'} glow="rgba(240,192,64,0.08)"/>
        <StatCard label="Commission earned" value={stats?.total_commission ?? '—'} delta="from add-ons" deltaUp glow="rgba(52,211,153,0.08)"/>
        <StatCard label="Conversion rate"   value={stats?.conversion_rate ?? '—'}/>
      </div>
      <div className="dash-section" style={{marginTop:20}}>
        <div className="dash-section-head"><div className="dash-section-title">🕐 Recent bookings</div></div>
        <table className="bookings-table">
          <thead>
            <tr><th>ID</th><th>Route</th><th>Passenger</th><th>Date</th><th>PNR</th><th>Source</th><th>Commission</th></tr>
          </thead>
          <tbody>
            {stats?.recent_bookings?.length ? stats.recent_bookings.map(b => (
              <tr key={b.id}>
                <td><span className="pnr-code">#{b.id}</span></td>
                <td><div className="route-cell">{b.origin_city||b.origin||'?'}<span className="route-arrow">→</span>{b.destination_city||b.destination||'?'}</div></td>
                <td>{b.name || <span style={{color:'var(--muted)'}}>—</span>}</td>
                <td>{b.departure_date || '—'}</td>
                <td><span className="pnr-code">{b.pnr || '—'}</span></td>
                <td><span className={`source-badge ${b.source === 'pdf_upload' ? 'src-pdf' : 'src-chat'}`}>{b.source === 'pdf_upload' ? 'PDF' : 'Chat'}</span></td>
                <td style={{color:'var(--green)',fontWeight:600}}>${b.commission_earned || 0}</td>
              </tr>
            )) : (
              <tr><td colSpan={7} className="empty-row">No bookings yet — upload a ticket or use the AI assistant</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="page-bottom"/>
    </>
  );
}

/* ─── Upload Page ─── */
function UploadPage() {
  const [dragging, setDragging]   = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult]       = useState(null);
  const [error, setError]         = useState(null);
  const fileRef                   = useRef();
  const ALLOWED_EXTS = ['.pdf', '.jpg', '.jpeg', '.png', '.webp'];
  const upload = async file => {
     const ext = '.' + (file?.name?.split('.').pop()?.toLowerCase() || '');
    if (!file || !ALLOWED_EXTS.includes(ext)) {
        setError('Please upload a PDF or image file (JPG, PNG, WEBP).');
        return;}
    setUploading(true); setError(null); setResult(null);
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await axios.post(`${API}/ticket/parse`, fd, {headers:{'Content-Type':'multipart/form-data'}});
      setResult(r.data);
    } catch(e) { setError(e.response?.data?.detail || 'Upload failed. Is the server running?'); }
    setUploading(false);
  };

  const conf      = result?.parsed?.confidence || 0;
  const confClass = conf >= .8 ? 'conf-high' : conf >= .5 ? 'conf-med' : 'conf-low';
  const confLabel = `${Math.round(conf * 100)}%${conf < .8 ? ' — review needed' : ' confident'}`;
  const fields    = result ? [
    {label:'Passenger',     value:result.parsed.name},
    {label:'PNR',           value:result.parsed.pnr,           mono:true},
    {label:'Flight',        value:result.parsed.flight_number, mono:true},
    {label:'Origin',        value:result.parsed.origin_city || result.parsed.origin},
    {label:'Destination',   value:result.parsed.destination_city || result.parsed.destination},
    {label:'Departure date',value:result.parsed.departure_date},
  ] : [];

  return (
    <>
      <div className="page-header">
        <div><div className="page-title">📄 Upload Ticket</div><div className="page-sub">Auto-parse flight tickets into your booking dashboard</div></div>
      </div>
      <div
        className={`upload-zone ${dragging ? 'drag' : ''}`}
        onDragOver={e=>{e.preventDefault();setDragging(true);}}
        onDragLeave={()=>setDragging(false)}
        onDrop={e=>{e.preventDefault();setDragging(false);const f=e.dataTransfer.files[0];if(f)upload(f);}}
        onClick={()=>fileRef.current?.click()}
      >
        <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" style={{display:'none'}} onChange={e=>{if(e.target.files[0])upload(e.target.files[0]);}}/>
        <div className="upload-icon">{uploading ? '⏳' : '🖼️'}</div>
        <div className="upload-title">{uploading ? 'Parsing your ticket…' : 'Drop your flight ticket PDF or image here'}</div>
        <div className="upload-sub">{uploading ? 'Extracting fields…' : 'Supports PDF, JPG, PNG · Air India, IndiGo, Emirates and more'}</div>
        <button className="upload-btn" disabled={uploading}>{uploading ? 'Uploading…' : 'Choose File'}</button>
      </div>
      {error && <div style={{margin:'0 28px 16px',padding:'12px 16px',background:'rgba(248,113,113,0.08)',border:'1px solid rgba(248,113,113,0.25)',borderRadius:'var(--r)',color:'var(--red)',fontSize:13}}>⚠️ {error}</div>}
      {result && (
        <div className="ticket-result">
          <div className="ticket-banner">
            <span style={{fontSize:18}}>✅</span>
            <div>
              <div style={{fontFamily:'var(--font-h)',fontWeight:700,fontSize:14}}>Ticket parsed — Booking #{result.booking_id}</div>
              <div style={{fontSize:11.5,color:'var(--muted)',marginTop:1}}>{result.message}</div>
            </div>
            <span className={`conf-badge ${confClass}`}>{confLabel}</span>
          </div>
          <div className="ticket-fields">
            {fields.map((f,i) => (
              <div key={i} className="ticket-field">
                <div className="tf-label">{f.label}</div>
                <div className={`tf-val ${f.mono ? 'mono' : ''} ${!f.value ? 'tf-empty' : ''}`}>{f.value || 'Not found'}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {result && <AddonsSection bookingId={result.booking_id}/>}
      <div className="page-bottom"/>
    </>
  );
}

/* ─── FIX 1: BookingDetailPage at TOP LEVEL (not nested inside App) ─── */
/* ─── FIX 2: Uses useParams() to read :bookingId from the URL        ─── */
function BookingDetailPage() {
  const { bookingId } = useParams();          // reads /booking/:bookingId from URL
  const [booking, setBooking] = useState(null);
  const [error, setError]     = useState(null);

  useEffect(() => {
    if (!bookingId) return;
    axios.get(`${API}/bookings/${bookingId}`)
      .then(r => setBooking(r.data))
      .catch(() => setError('Booking not found.'));
  }, [bookingId]);

  if (error) return (
    <div style={{padding:'40px 28px',color:'var(--red)'}}>⚠️ {error}</div>
  );
  if (!booking) return (
    <div style={{padding:'40px 28px',color:'var(--muted)'}}>Loading booking…</div>
  );

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">Booking #{booking.id}</div>
          <div className="page-sub">
            {booking.origin_city || booking.origin} → {booking.destination_city || booking.destination}
            {booking.departure_date ? ` · ${booking.departure_date}` : ''}
          </div>
        </div>
      </div>
      {/* Parsed ticket fields */}
      <div className="ticket-result" style={{margin:'20px 28px'}}>
        <div className="ticket-banner">
          <span style={{fontSize:18}}>✈️</span>
          <div>
            <div style={{fontFamily:'var(--font-h)',fontWeight:700,fontSize:14}}>{booking.name}</div>
            <div style={{fontSize:11.5,color:'var(--muted)',marginTop:1}}>Flight {booking.flight_number} · PNR {booking.pnr}</div>
          </div>
          <span className="conf-badge conf-high" style={{marginLeft:'auto'}}>Confirmed</span>
        </div>
        <div className="ticket-fields">
          {[
            {label:'Passenger',    value:booking.name},
            {label:'PNR',         value:booking.pnr,           mono:true},
            {label:'Flight',      value:booking.flight_number, mono:true},
            {label:'Origin',      value:booking.origin_city || booking.origin},
            {label:'Destination', value:booking.destination_city || booking.destination},
            {label:'Departure',   value:booking.departure_date},
          ].map((f,i) => (
            <div key={i} className="ticket-field">
              <div className="tf-label">{f.label}</div>
              <div className={`tf-val ${f.mono ? 'mono' : ''} ${!f.value ? 'tf-empty' : ''}`}>
                {f.value || 'Not found'}
              </div>
            </div>
          ))}
        </div>
      </div>
      {/* Add-ons selection */}
      <AddonsSection bookingId={booking.id}/>
      <div className="page-bottom"/>
    </>
  );
}

/* ─── Shell with Sidebar (used by all non-detail pages) ─── */
/* ─── FIX 3: Sidebar uses useNavigate() + useLocation() instead of  ─── */
/*            a local `tab` state, so the URL stays in sync            */
function AppShell({ children }) {
  const navigate  = useNavigate();
  const location  = useLocation();
  const tab       = location.pathname.replace('/', '') || 'dashboard';

  const navItems = [
    { id:'dashboard', icon:'📊', label:'Dashboard' },
    { id:'upload',    icon:'📄', label:'Upload Ticket' },
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-icon">✈️</div>
          <span className="logo-name">Tripy AI</span>
          <span className="logo-ver">v3.0</span>
        </div>
        <div className="nav-section">
          <div className="nav-label">Navigation</div>
          {navItems.map(n => (
            <div
              key={n.id}
              className={`nav-item ${tab === n.id ? 'active' : ''}`}
              onClick={() => navigate(`/${n.id}`)}
            >
              <span className="nav-icon">{n.icon}</span>{n.label}
            </div>
          ))}
        </div>
        <div className="sidebar-footer">
          <button
            className={`ai-btn ${tab === 'chat' ? 'active' : ''}`}
            onClick={() => navigate('/chat')}
          >
            <span style={{fontSize:16}}>💬</span>
            AI Assistant
            <span className="pulse-dot"/>
          </button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

/* ─── Root App — React Router wired up ─── */
export default function App() {
  return (
    <>
      <FontLoader/>
      <style>{CSS}</style>
      <BrowserRouter>
        <Routes>
          {/* Pages with sidebar shell */}
          <Route path="/" element={<AppShell><DashboardPage/></AppShell>}/>
          <Route path="/dashboard" element={<AppShell><DashboardPage/></AppShell>}/>
          <Route path="/upload"    element={<AppShell><UploadPage/></AppShell>}/>
          <Route path="/chat"      element={<AppShell><FullScreenChat/></AppShell>}/>

          {/* Deep-link from Telegram — no sidebar needed, just the booking + addons */}
          <Route path="/booking/:bookingId" element={<AppShell><BookingDetailPage/></AppShell>}/>
        </Routes>
      </BrowserRouter>
    </>
  );
}
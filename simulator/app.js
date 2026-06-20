// Change this to http://<PI_IP>:5055 when the API runs on a Raspberry Pi.
const API_BASE = "http://localhost:5055";

let devices = [];
let user = { x: 50, y: 50 };
let nearestDevice = null;

const DEVICE_POSITIONS = {
  'light.bedroom_light': { style: { left: '8%', top: '12%' }, icon: '💡', short: 'Bedroom Light' },
  'climate.bedroom_ac': { style: { right: '8%', top: '12%' }, icon: '❄️', short: 'Bedroom AC' },
  'sensor.bedroom_temperature': { style: { left: '8%', bottom: '14%' }, icon: '🌡️', short: 'Bedroom Temp' },
  'sensor.bedroom_humidity': { style: { right: '8%', bottom: '14%' }, icon: '💧', short: 'Bedroom Humidity' },
  'switch.living_room_ceiling_fan': { style: { left: '50%', top: '10%', transform: 'translateX(-50%)' }, icon: '🌀', short: 'Ceiling Fan' },
  'binary_sensor.living_room_camera_presence': { style: { left: '8%', top: '12%' }, icon: '📷', short: 'Camera Presence' },
  'climate.living_room_ac': { style: { right: '8%', top: '12%' }, icon: '❄️', short: 'Living AC' },
  'binary_sensor.front_door_lock': { style: { left: '4%', top: '48%' }, icon: '🚪', short: 'Front Door' },
  'media_player.living_room_tv': { style: { left: '50%', bottom: '8%', transform: 'translateX(-50%)' }, icon: '📺', short: 'Living TV' },
  'sensor.living_room_temperature': { style: { left: '8%', bottom: '12%' }, icon: '🌡️', short: 'Living Temp' },
  'sensor.living_room_humidity': { style: { right: '8%', bottom: '12%' }, icon: '💧', short: 'Living Humidity' },
  'switch.bathroom_water_heater': { style: { right: '8%', top: '12%' }, icon: '🚿', short: 'Water Heater' },
  'sensor.kitchen_washing_machine_status': { style: { left: '8%', bottom: '12%' }, icon: '🧺', short: 'Washer Status' },
};

const roomContainers = {
  bedroom: document.getElementById('bedroomNodes'),
  living_room: document.getElementById('livingRoomNodes'),
  bathroom: document.getElementById('bathroomNodes'),
  kitchen: document.getElementById('kitchenNodes'),
};

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function setStatus(text) { document.getElementById('status').textContent = text; }
function val(id) { return document.getElementById(id).value; }
function numOrNull(id) { const v = val(id); return v === '' ? null : Number(v); }

function contextFromForm() {
  return {
    sim_time: val('sim_time'),
    outdoor_temperature: Number(val('outdoor_temperature')),
    outdoor_humidity: Number(val('outdoor_humidity')),
    living_room_temperature: Number(val('living_room_temperature')),
    living_room_humidity: Number(val('living_room_humidity')),
    bedroom_temperature: Number(val('bedroom_temperature')),
    bedroom_humidity: Number(val('bedroom_humidity')),
    presence_home: val('presence_home') === 'true',
    arrival_status: val('arrival_status'),
    predicted_arrival_minutes: numOrNull('predicted_arrival_minutes'),
    minutes_after_expected_arrival: Number(val('minutes_after_expected_arrival') || 0),
  };
}

function applyContextToForm(ctx) {
  for (const [k, v] of Object.entries(ctx)) {
    const el = document.getElementById(k);
    if (!el) continue;
    el.value = v === null || v === undefined ? '' : String(v);
  }
  document.getElementById('outdoorTemp').textContent = `Outdoor Temp: ${ctx.outdoor_temperature}°C`;
  document.getElementById('outdoorHumidity').textContent = `Outdoor Humidity: ${ctx.outdoor_humidity}%`;
}

function renderDevices(ctx = {}) {
  Object.values(roomContainers).forEach(c => c.innerHTML = '');
  devices.forEach(d => {
    const el = document.createElement('button');
    const stateClass = d.current_state === 'on' ? 'device-on' : 'device-off';
    const controlClass = d.control_level === 'observe_only' ? 'device-observe-only' : `device-${d.control_level}`;
    const pos = DEVICE_POSITIONS[d.entity_id] || { style: { left: '10%', top: '10%' }, icon: '🔘', short: d.friendly_name };
    el.className = `device-node ${controlClass} ${stateClass}`;
    el.dataset.entity = d.entity_id;
    Object.assign(el.style, pos.style);
    el.title = `${d.entity_id} | ${d.control_level} | ${d.risk_level}`;
    el.innerHTML = labelForDevice(d, ctx);
    el.onclick = () => manualActionDevice(d);
    roomContainers[d.room]?.appendChild(el);
  });
  updateNearest();
}

function labelForDevice(d, ctx) {
  const pos = DEVICE_POSITIONS[d.entity_id] || { icon: '🔘', short: d.friendly_name };
  let state = d.current_state ?? 'unknown';
  if (d.entity_id === 'sensor.living_room_temperature') state = `${ctx.living_room_temperature ?? d.current_state}°C`;
  if (d.entity_id === 'sensor.living_room_humidity') state = `${ctx.living_room_humidity ?? d.current_state}%`;
  if (d.entity_id === 'sensor.bedroom_temperature') state = `${ctx.bedroom_temperature ?? d.current_state}°C`;
  if (d.entity_id === 'sensor.bedroom_humidity') state = `${ctx.bedroom_humidity ?? d.current_state}%`;
  return `<span class="device-title">${pos.icon} ${pos.short}</span><span class="device-state">${state}</span>`;
}

function renderRequests(requests) {
  const root = document.getElementById('requestCards');
  root.innerHTML = requests.length ? '' : '<p class="muted">No pending requests.</p>';
  requests.forEach(r => {
    const card = document.createElement('div');
    card.className = 'card request-card';
    card.innerHTML = `<h3 class="request-title">🤖 Agent Request</h3><p>Thiết bị: ${r.entity_id}</p><p>Hành động: ${r.requested_action}</p><p>Confidence: ${Math.round((r.confidence || 0) * 100)}%</p><p>Lý do: ${r.reason_code}</p><div class="buttons request-actions"><button data-yes="${r.request_id}">Yes</button><button data-no="${r.request_id}">No</button></div>`;
    root.appendChild(card);
  });
  root.querySelectorAll('[data-yes]').forEach(b => b.onclick = () => respond(b.dataset.yes, 'yes'));
  root.querySelectorAll('[data-no]').forEach(b => b.onclick = () => respond(b.dataset.no, 'no'));
}

function renderLogs(logs) {
  const root = document.getElementById('logs');
  root.innerHTML = '';
  logs.forEach(l => {
    const div = document.createElement('div');
    div.className = `log log-item ${l.log_type}`;
    const t = (l.sim_time || l.timestamp || '').slice(11, 16);
    div.innerHTML = `<strong class="log-title">[${t}] ${l.log_type}</strong><br><span class="log-entity">${l.entity_id || ''}</span><br><span class="log-message">${truncateText(l.message)}</span>`;
    root.appendChild(div);
  });
}

function truncateText(text, max = 110) {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

async function refresh() {
  try {
    const state = await api('/api/state');
    devices = state.devices;
    applyContextToForm(state.sim_context);
    renderDevices(state.sim_context);
    renderRequests(state.pending_requests);
    renderLogs(state.recent_logs);
    setStatus('Connected');
  } catch (e) { setStatus(`Error: ${e.message}`); }
}

async function applyContext() {
  await api('/api/sim-context', { method: 'POST', body: JSON.stringify(contextFromForm()) });
  await refresh();
}
async function evaluateContext() { await api('/api/evaluate-context', { method: 'POST' }); await refresh(); }
async function runScenario(name) { await api(`/api/scenarios/${name}`, { method: 'POST' }); await refresh(); }
async function respond(id, response) { await api(`/api/requests/${id}/respond`, { method: 'POST', body: JSON.stringify({ response }) }); await refresh(); }

function updateUserDot() {
  const dot = document.getElementById('userDot');
  dot.style.left = `${user.x}%`;
  dot.style.top = `${user.y}%`;
}

function updateNearest() {
  document.querySelectorAll('.device-node').forEach(d => d.classList.remove('device-highlighted', 'highlighted'));
  const map = document.getElementById('houseMap');
  const mapRect = map.getBoundingClientRect();
  const userPx = {
    x: mapRect.left + (user.x / 100) * mapRect.width,
    y: mapRect.top + (user.y / 100) * mapRect.height,
  };
  let best = null;
  let bestDistance = Infinity;
  document.querySelectorAll('.device-node').forEach(node => {
    const rect = node.getBoundingClientRect();
    const center = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    const distance = Math.hypot(center.x - userPx.x, center.y - userPx.y);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = devices.find(d => d.entity_id === node.dataset.entity);
    }
  });
  nearestDevice = best || null;
  if (nearestDevice) document.querySelector(`[data-entity="${nearestDevice.entity_id}"]`)?.classList.add('device-highlighted', 'highlighted');
}

async function manualActionDevice(device) {
  if (!device) return;
  if (device.control_level === 'observe_only') {
    setStatus('Observe-only device, cannot control');
    return;
  }
  const action = device.current_state === 'on' ? 'turn_off' : 'turn_on';
  setStatus(`Sending ${action} for ${device.entity_id} at ${val('sim_time')}`);
  await api('/api/user-action', {
    method: 'POST',
    body: JSON.stringify({
      entity_id: device.entity_id,
      action,
      source: 'simulator',
      sim_time: val('sim_time'),
    }),
  });
  await refresh();
}

async function manualActionNearest() { await manualActionDevice(nearestDevice); }

document.getElementById('applyContext').onclick = applyContext;
document.getElementById('evaluateContext').onclick = evaluateContext;
document.querySelectorAll('[data-scenario]').forEach(b => b.onclick = () => runScenario(b.dataset.scenario));
document.addEventListener('keydown', (e) => {
  const step = 5;
  if (e.key === 'ArrowLeft') user.x = Math.max(5, user.x - step);
  else if (e.key === 'ArrowRight') user.x = Math.min(95, user.x + step);
  else if (e.key === 'ArrowUp') user.y = Math.max(5, user.y - step);
  else if (e.key === 'ArrowDown') user.y = Math.min(95, user.y + step);
  else if (e.code === 'Space') { e.preventDefault(); manualActionNearest(); return; }
  else return;
  e.preventDefault();
  updateUserDot(); updateNearest();
});

window.addEventListener('resize', updateNearest);

updateUserDot();
refresh();
setInterval(refresh, 5000);
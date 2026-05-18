let map;
let markers = [];

async function initMap() {
    // Default fallback to US
    let initialCenter = { lat: 39.8283, lng: -98.5795 };
    let initialZoom = 4;

    map = new google.maps.Map(document.getElementById("map"), {
        center: initialCenter,
        zoom: initialZoom,
        mapId: 'DEMO_MAP_ID',
        disableDefaultUI: true,
        zoomControl: true,
    });

    // Setup the map-click listener ONCE here to close any open info popup
    // Must be done after map is initialized, not inside plotData (which runs repeatedly)
    map.addListener('click', () => {
        if (window.activeInfoWindow) window.activeInfoWindow.close();
    });

    // Show search button when map is panned/zoomed
    map.addListener('dragend', () => { if (window.showSearchButton) window.showSearchButton(); });
    map.addListener('zoom_changed', () => { if (window.showSearchButton) window.showSearchButton(); });

    // Also keep direct click on the button (handled in map.html as searchArea())
    window.fetchData = loadMapData;
    // Try HTML5 geolocation
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (position) => {
                const pos = {
                    lat: position.coords.latitude,
                    lng: position.coords.longitude,
                };
                // Store for distance-sort in record list
                window.userLat = pos.lat;
                window.userLng = pos.lng;
                setTimeout(() => {
                    google.maps.event.trigger(map, 'resize');
                    map.setCenter(pos);
                    map.setZoom(10);
                    google.maps.event.addListenerOnce(map, 'idle', loadMapData);
                }, 150);
            },
            () => { tryIPFallback(); },
            { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
        );
    } else {
        tryIPFallback();
    }
}

async function tryIPFallback() {
    try {
        const res = await fetch('https://ipapi.co/json/');
        const data = await res.json();
        if (data.latitude && data.longitude) {
            window.userLat = data.latitude;
            window.userLng = data.longitude;
            map.setCenter({ lat: data.latitude, lng: data.longitude });
            map.setZoom(8);
        }
    } catch (e) {
        console.error('IP fallback failed:', e);
    } finally {
        google.maps.event.addListenerOnce(map, 'idle', loadMapData);
    }
}

async function loadMapData() {
    try {
        const bounds = map.getBounds();
        if (!bounds) {
            console.log("Map bounds not yet available. Skipping load.");
            return;
        }
        const sw = bounds.getSouthWest();
        const ne = bounds.getNorthEast();
        const center = map.getCenter();

        // 200 miles is approx 3 degrees of latitude/longitude.
        // If viewport is larger than ~200 miles, we cap the SYNC area to the central 200 miles
        // to avoid hitting Zoho API limits or syncing too many records at once.
        let sync_min_lat = sw.lat();
        let sync_max_lat = ne.lat();
        let sync_min_lng = sw.lng();
        let sync_max_lng = ne.lng();

        if (ne.lat() - sw.lat() > 3.0) {
            sync_min_lat = center.lat() - 1.5;
            sync_max_lat = center.lat() + 1.5;
            sync_min_lng = center.lng() - 1.5;
            sync_max_lng = center.lng() + 1.5;
        }

        const params = new URLSearchParams({
            min_lat: sw.lat(),
            max_lat: ne.lat(),
            min_lng: sw.lng(),
            max_lng: ne.lng(),
            sync_min_lat: sync_min_lat,
            sync_max_lat: sync_max_lat,
            sync_min_lng: sync_min_lng,
            sync_max_lng: sync_max_lng,
            sync: 'true'
        });

        const res = await fetch('/api/map-data?' + params.toString());
        if (!res.ok) {
            if (res.status === 401) window.location.href = '/login';
            throw new Error('Failed to fetch data');
        }
        const data = await res.json();
        window.lastMapData = data;

        const filtered = filterDuplicates(data);
        window.lastMapData = filtered;

        plotData(filtered);
        updateLegend(filtered);
        if (window.updateRecordList) window.updateRecordList(filtered);
    } catch (e) {
        console.error(e);
    }
}

/**
 * Filter duplicate child records that overlap with their parent module's markers.
 * Logic (per child module with an active duplicate_filter):
 *   1. Group child records by their parent link ID (_dup_parent_id).
 *   2. For each parent that is actually on the map:
 *      a. If any child has override_checkbox = true → hide THAT child (it IS the primary).
 *      b. Otherwise → hide the child whose primary_code_field = primary_code_value (e.g. "0").
 */
function filterDuplicates(data) {
    // Find modules with an active filter
    const filterModules = [...new Set(
        data.filter(p => p.filter_config?.enabled).map(p => p.api_module_name)
    )];
    if (filterModules.length === 0) return data;

    const toHide = new Set();

    filterModules.forEach(modName => {
        const sample = data.find(p => p.api_module_name === modName && p.filter_config?.enabled);
        const fc = sample.filter_config;

        const parentModName  = fc.parent_module;
        const primaryLabel   = fc.primary_code_field_label;
        const primaryValue   = String(fc.primary_code_value ?? '0');
        const overrideLabel  = fc.override_checkbox_field_label;

        // Index parent records by their Zoho ID
        const parentById = {};
        data.filter(p => p.api_module_name === parentModName)
            .forEach(p => { parentById[p.id] = p; });

        // Group children by parent link ID
        const childrenByParent = {};
        data.filter(p => p.api_module_name === modName).forEach(child => {
            const pid = child.record_data['_dup_parent_id'];
            if (pid) {
                if (!childrenByParent[pid]) childrenByParent[pid] = [];
                childrenByParent[pid].push(child);
            }
        });

        // Determine which children to hide per parent
        Object.entries(childrenByParent).forEach(([parentId, children]) => {
            if (!parentById[parentId]) return; // Parent not on map — keep all

            // Check for override checkbox (e.g. "Show Address on Map" = true)
            const withOverride = overrideLabel
                ? children.filter(c => String(c.record_data[overrideLabel]).toLowerCase() === 'true')
                : [];

            const toDeduplicate = withOverride.length > 0
                ? withOverride  // The override-checked one IS the primary duplicate
                : children.filter(c => String(c.record_data[primaryLabel]) === primaryValue);

            toDeduplicate.forEach(c => toHide.add(c.id));
        });
    });

    return data.filter(p => !toHide.has(p.id));
}

const ICON_PATHS = {
    'pin': "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5S10.62 6.5 12 6.5s2.5 1.12 2.5 2.5S13.38 11.5 12 11.5z",
    'building': "M3 21h18M6 21V7a3 3 0 0 1 3-3h6a3 3 0 0 1 3 3v14M9 8v.01M14 8v.01M9 12v.01M14 12v.01M9 16v.01M14 16v.01",
    'building_standard': "M3 21h18M6 21V7a3 3 0 0 1 3-3h6a3 3 0 0 1 3 3v14M10 8h4M10 12h4M10 16h4",
    'building-community': "M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16M8 7h3M13 7h3M8 11h3M13 11h3M8 15h3M13 15h3",
    'person': "M12 12c2.2 0 4-1.8 4-4s-1.8-4-4-4-4 1.8-4 4 1.8 4 4 4zm0 2c-2.7 0-8 1.3-8 4v2h16v-2c0-2.7-5.3-4-8-4z",
    'star': "M12 2l3.1 6.3 7 1-5 4.9 1.2 7-6.3-3.3-6.3 3.3 1.2-7-5-4.9 7-1z",
    'home': "M3 12l9-9 9 9M5 12v8a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-8",
    'factory': "M3 21h18M3 7l7 5V7l7 5V7l4 3v11H3V7z",
    'building3D': [
        "M2 14l12 0",          // Bottom frame line
        "M6 5.33l.67 0",       // Windows Row 1
        "M6 8l.67 0",          // Windows Row 2
        "M6 10.67l.67 0",      // Windows Row 3
        "M9.33 5.33l.67 0",    // Windows Row 1 (Right)
        "M9.33 8l.67 0",       // Windows Row 2 (Right)
        "M9.33 10.67l.67 0",   // Windows Row 3 (Right)
        "M3.33 14v-10.67a1.33 1.33 0 0 1 1.33 -1.33h6.67a1.33 1.33 0 0 1 1.33 1.33v10.67", // Outline
        "M7.33 14v-2.67h1.33v2.67" // Door
    ]
};

let markerCluster;
// Single shared infoWindow — stored on window so inline onclick= handlers can access it
window.activeInfoWindow = null;

function plotData(data) {
    // Clear existing markers
    markers.forEach(m => m.setMap(null));
    markers = [];
    if (markerCluster) {
        markerCluster.clearMarkers();
    }

    const bounds = new google.maps.LatLngBounds();

    // Reuse a single InfoWindow
    if (!window.activeInfoWindow) {
        window.activeInfoWindow = new google.maps.InfoWindow();
    }

    // Always reset marker lookup so stale markers from previous loads don't linger
    window.markersById = {};

    const visibleData = data.filter(item => !(window.hiddenModules && window.hiddenModules.has(item.module)));

    visibleData.forEach(item => {
        const position = { lat: item.lat, lng: item.lng };

        // Custom SVG Marker to use the dynamically configured color and icon
        let path = ICON_PATHS[item.icon] || ICON_PATHS['pin'];
        
        if (Array.isArray(path)) {
            path = path.join(' ');
        }

        const svgMarker = {
            path: path,
            fillColor: item.color || "#3b82f6",
            fillOpacity: 0.85,
            strokeWeight: 1.4,
            strokeColor: "#FFFFFF",
            rotation: 0,
            scale: 1.4,
            anchor: new google.maps.Point(12, 12),
        };

        // Specific adjustments for better visual alignment
        if (item.icon === 'pin' || !item.icon) {
            svgMarker.anchor = new google.maps.Point(12, 22);
            svgMarker.scale = 1.3;
        } else if (item.icon === 'building3D') {
            svgMarker.anchor = new google.maps.Point(8, 8);
            svgMarker.scale = 2.0;
        } else if (item.icon && item.icon.startsWith('building')) {
            svgMarker.strokeWeight = 1.4;
            svgMarker.fillOpacity = 0.9;
            svgMarker.scale = 1.5;
        }

        const marker = new google.maps.Marker({
            position: position,
            map: map,
            icon: svgMarker,
            title: item.name
        });

        bounds.extend(position);

        marker.addListener('click', () => {
            const content = window.buildPopupContent(item);
            window.activeInfoWindow.setContent(content);
            window.activeInfoWindow.open(map, marker);
        });

        markers.push(marker);
        window.markersById[item.id] = { marker, item };
    });

    // Initialize or Update Clusterer only if visible markers >= 50
    if (typeof markerClusterer !== 'undefined' && markers.length >= 50) {
        markerCluster = new markerClusterer.MarkerClusterer({ 
            markers, 
            map,
            onClusterClick: (event, cluster, map) => {
                // Prevent auto-zoom on click as requested
            }
        });
    } else {
        // If not clustering (less than 50 markers), show them all individually
        markers.forEach(m => m.setMap(map));
    }
}

// ── Shared popup content builder ──────────────────────────────────────────────
window.buildPopupContent = function(item) {
    const addressKeys = ['Address', 'City', 'State', 'Zip', 'Country', 'Latitude', 'Longitude'];
    let content = `<div class="info-window"><h3>${item.name}</h3><p style="margin-bottom:8px;"><strong>Module:</strong> ${item.module}</p><div class="info-details">`;

    let addressHtml = '';
    addressKeys.forEach(k => { if (item.record_data[k]) addressHtml += `<div style="margin-bottom:2px;"><strong>${k}:</strong> ${item.record_data[k]}</div>`; });
    if (addressHtml) content += `<div style="background:rgba(255,255,255,0.05);padding:8px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);margin-bottom:8px;"><div style="font-size:0.75rem;color:#94a3b8;text-transform:uppercase;margin-bottom:4px;font-weight:600;">Location</div>${addressHtml}</div>`;

    const addKeys = Object.keys(item.record_data).filter(k => !addressKeys.includes(k) && !k.startsWith('_')).sort();
    let addHtml = '';
    addKeys.forEach(k => { if (item.record_data[k]) addHtml += `<div style="margin-bottom:2px;"><strong>${k}:</strong> ${item.record_data[k]}</div>`; });
    if (addHtml) content += `<div style="background:rgba(255,255,255,0.02);padding:8px;border-radius:6px;border:1px solid rgba(255,255,255,0.05);margin-bottom:12px;"><div style="font-size:0.75rem;color:#94a3b8;text-transform:uppercase;margin-bottom:4px;font-weight:600;">Additional Info</div>${addHtml}</div>`;

    const safeName = item.name.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    const zohoAppLink = `zohocrm://crm/${encodeURIComponent(item.api_module_name || item.module)}/${item.id}`;

    content += `<div class="info-actions" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;">
        <button class="btn-primary" style="font-size:0.7rem;padding:0.25rem;" onclick="window.activeInfoWindow&&window.activeInfoWindow.close();window.getDirections(${item.lat},${item.lng})">Directions</button>
        <button class="btn-secondary" style="font-size:0.7rem;padding:0.25rem;color:#1e293b;" onclick="window.activeInfoWindow&&window.activeInfoWindow.close();window.addToRoute('${item.id}','${safeName}',${item.lat},${item.lng})">Add to Route</button>
        <button class="btn-secondary" style="font-size:0.7rem;padding:0.25rem;color:#1e293b;" onclick="window.activeInfoWindow&&window.activeInfoWindow.close();window.open('${item.zoho_link}','_blank')">Open Web</button>
        <button class="btn-secondary" style="font-size:0.7rem;padding:0.25rem;color:#1e293b;display:flex;align-items:center;justify-content:center;gap:4px;" onclick="window.syncSingleRecord('${item.api_module_name||item.module}','${item.id}',this)"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 1 0 2.13-5.88L2 10"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 1 0-2.13 5.88l3.13-3.88"/></svg>Sync</button>
        ${isMobile ? `<button class="btn-primary" style="font-size:0.7rem;padding:0.25rem;grid-column:span 2;" onclick="window.activeInfoWindow&&window.activeInfoWindow.close();window.location.href='${zohoAppLink}'">Open in Zoho App</button>` : ''}
    </div></div></div>`;
    return content;
};

// Open the map marker for a record from the list drawer
window.focusMapMarker = function(id) {
    const sid = String(id);
    console.log('[focusMapMarker] called | id:', sid,
                '| markersById entries:', window.markersById ? Object.keys(window.markersById).length : 'undefined');

    // Primary path — marker is in the current viewport lookup
    const entry = window.markersById && (window.markersById[sid] || window.markersById[id]);
    if (entry) {
        console.log('[focusMapMarker] marker found, opening popup');
        const { marker, item } = entry;
        map.panTo({ lat: item.lat, lng: item.lng });
        if (map.getZoom() < 14) map.setZoom(14);
        if (!window.activeInfoWindow) window.activeInfoWindow = new google.maps.InfoWindow();
        window.activeInfoWindow.setContent(window.buildPopupContent(item));
        window.activeInfoWindow.open(map, marker);
        return;
    }

    // Fallback — marker outside current viewport
    console.warn('[focusMapMarker] id not in markersById, searching lastMapData …');
    const fallback = window.lastMapData && window.lastMapData.find(d => String(d.id) === sid);
    if (fallback) {
        console.log('[focusMapMarker] fallback found:', fallback.name);
        map.panTo({ lat: fallback.lat, lng: fallback.lng });
        map.setZoom(15);
        google.maps.event.addListenerOnce(map, 'idle', function() {
            const retry = window.markersById && (window.markersById[sid] || window.markersById[id]);
            if (!window.activeInfoWindow) window.activeInfoWindow = new google.maps.InfoWindow();
            window.activeInfoWindow.setContent(window.buildPopupContent(fallback));
            if (retry) {
                window.activeInfoWindow.open(map, retry.marker);
            } else {
                window.activeInfoWindow.setPosition({ lat: fallback.lat, lng: fallback.lng });
                window.activeInfoWindow.open(map);
            }
        });
    } else {
        console.error('[focusMapMarker] record not found anywhere. id=', sid);
    }
};


function updateLegend(data) {
    const legend = document.getElementById('cat-list');
    if (!legend) return;
    legend.innerHTML = '';

    const moduleCounts = {};
    data.forEach(item => { moduleCounts[item.module] = (moduleCounts[item.module] || 0) + 1; });

    let configuredModules = window.configuredModules || [];
    const moduleColorByLabel = {};
    for (let cfg of configuredModules) {
        moduleColorByLabel[cfg.module_name] = cfg.marker_color;
        if (cfg.module_label) moduleColorByLabel[cfg.module_label] = cfg.marker_color;
    }
    data.forEach(item => { if (item.color && !moduleColorByLabel[item.module]) moduleColorByLabel[item.module] = item.color; });

    if (configuredModules.length === 0) {
        configuredModules = Object.keys(moduleCounts).map(mod => ({ module_name: mod, marker_color: moduleColorByLabel[mod] || '#4f46e5' }));
    }

    const eyeVisible = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
    const eyeHidden  = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;

    for (let config of configuredModules) {
        const mod = config.module_name;
        const color = config.marker_color || moduleColorByLabel[mod] || '#4f46e5';
        const count = moduleCounts[mod] || moduleCounts[config.module_label] || 0;
        const isVisible = !(window.hiddenModules && window.hiddenModules.has(mod));
        const safeModule = mod.replace(/'/g, "\\'");

        const row = document.createElement('div');
        row.className = 'cat-row';
        row.innerHTML = `
            <span class="cat-dot" style="background:${color};"></span>
            <span class="cat-label">${mod}</span>
            <span class="cat-count">${count}</span>
            <button class="cat-eye" id="eye-${mod.replace(/[^a-z0-9]/gi,'_')}"
                    onclick="window.toggleModuleVisibility('${safeModule}', ${isVisible})" title="${isVisible ? 'Hide' : 'Show'} ${mod}">
                ${isVisible ? eyeVisible : eyeHidden}
            </button>
            <button class="cat-sync" onclick="syncSingleModule('${safeModule}', this)">Sync</button>
        `;
        legend.appendChild(row);
    }
}

window.syncSingleModule = async function(moduleName, btn) {
    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = `<span class="spinner" style="width:10px;height:10px;"></span>`;
    
    // Also update the global status indicator if present
    const status = document.getElementById('sync-status');
    if (status) {
        status.style.color = 'var(--text-secondary)';
        status.textContent = 'Syncing ' + moduleName + '...';
    }

    try {
        const res = await fetch('/api/sync-module/' + encodeURIComponent(moduleName), { method: 'POST' });
        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.error || 'Sync failed');
        }
        const data = await res.json();
        if (status) {
            status.style.color = 'var(--success)';
            status.textContent = 'Synced ' + data.synced + ' ' + moduleName + ' records!';
        }
        btn.innerHTML = '✓';
        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
        // Refresh the map data
        window.fetchData();
    } catch (e) {
        console.error(e);
        if (status) {
            status.style.color = 'var(--error)';
            status.textContent = 'Failed to sync ' + moduleName;
        }
        btn.innerHTML = '✗';
        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 3000);
    }
};

window.toggleModuleVisibility = function(moduleName, makeHidden) {
    // makeHidden=true means we want to HIDE it (eye was visible, user clicked to hide)
    if (makeHidden) {
        window.hiddenModules.add(moduleName);
    } else {
        window.hiddenModules.delete(moduleName);
    }
    // Re-plot data to apply visibility changes
    if (window.lastMapData) {
        plotData(window.lastMapData);
        updateLegend(window.lastMapData);
    }
};

// ROUTING LOGIC
window.routeStops = []; // { id, name, lat, lng, pinnedPos: null | number }

window.getDirections = function (lat, lng) {
    const url = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
    window.open(url, '_blank');
};

window.addToRoute = function (id, name, lat, lng) {
    if (window.routeStops.length >= 10) {
        alert("Google Maps only supports a maximum of 10 stops per route.");
        return;
    }
    if (window.routeStops.find(s => s.id === id)) {
        alert(`"${name}" is already in your route!`);
        return;
    }
    window.routeStops.push({ id, name, lat, lng, pinnedPos: null });
    window.renderRoutePlanner();
};

// Fix 4: Clear all route stops at once
window.clearRoute = function () {
    window.routeStops = [];
    window.renderRoutePlanner();
};

window.removeRouteStop = function (index) {
    window.routeStops.splice(index, 1);
    window.renderRoutePlanner();
};

window.setPinnedPos = function (index, val) {
    const num = val === '' ? null : parseInt(val, 10);
    if (num !== null && (num < 1 || num > window.routeStops.length)) {
        window.routeStops[index].pinnedPos = null;
    } else {
        window.routeStops[index].pinnedPos = num;
    }
};

function haversineKm(a, b) {
    const R = 6371;
    const dLat = (b.lat - a.lat) * Math.PI / 180;
    const dLng = (b.lng - a.lng) * Math.PI / 180;
    const x = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(a.lat * Math.PI / 180) * Math.cos(b.lat * Math.PI / 180) *
        Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

function optimizeRoute(stops, userLat, userLng) {
    const n = stops.length;
    if (n <= 1) return stops;

    // Build pinned map: pinnedPos (1-indexed) -> stop index in original list
    const pinnedSlots = {}; // slot (0-indexed) -> stop
    const freeStops = [];
    stops.forEach(s => {
        if (s.pinnedPos !== null) {
            pinnedSlots[s.pinnedPos - 1] = s;
        } else {
            freeStops.push(s);
        }
    });

    // Nearest-neighbor on free stops, starting from user location
    const start = { lat: userLat, lng: userLng };
    const ordered = [];
    const remaining = [...freeStops];

    let current = start;
    while (remaining.length > 0) {
        let bestIdx = 0;
        let bestDist = haversineKm(current, remaining[0]);
        for (let i = 1; i < remaining.length; i++) {
            const d = haversineKm(current, remaining[i]);
            if (d < bestDist) { bestDist = d; bestIdx = i; }
        }
        current = remaining[bestIdx];
        ordered.push(remaining.splice(bestIdx, 1)[0]);
    }

    // Build final array of n slots, inserting pinned stops then free ones
    const result = new Array(n).fill(null);
    for (const [slot, stop] of Object.entries(pinnedSlots)) {
        result[parseInt(slot)] = stop;
    }
    let freeIdx = 0;
    for (let i = 0; i < n; i++) {
        if (result[i] === null) {
            result[i] = ordered[freeIdx++];
        }
    }
    return result;
}

window.renderRoutePlanner = function () {
    const list  = document.getElementById('route-stops-list');
    const stats = document.getElementById('route-stats');

    if (typeof window.updateRouteBadge === 'function') window.updateRouteBadge(window.routeStops.length);

    if (!list) return;

    if (window.routeStops.length === 0) { list.innerHTML = ''; if (stats) stats.textContent = '0 stops'; return; }

    if (stats) stats.textContent = `${window.routeStops.length} stop${window.routeStops.length === 1 ? '' : 's'} · auto-optimize`;

    list.innerHTML = '';
    window.routeStops.forEach((stop, idx) => {
        const el = document.createElement('div');
        el.className = 'route-stop-item';
        let pinOptions = `<option value="">Auto</option>`;
        for (let p = 1; p <= window.routeStops.length; p++) {
            pinOptions += `<option value="${p}" ${stop.pinnedPos === p ? 'selected' : ''}>Stop #${p}</option>`;
        }
        el.innerHTML = `
            <div class="route-stop-name" title="${stop.name}">
                <span style="color:var(--primary);font-weight:600;">${idx + 1}.</span> ${stop.name}
                <div style="margin-top:3px;">
                    <label style="font-size:.68rem;color:#94a3b8;">Position: </label>
                    <select class="pin-select" onchange="window.setPinnedPos(${idx}, this.value)"
                        style="font-size:.7rem;padding:1px 4px;border-radius:4px;background:rgba(15,23,42,.8);border:1px solid rgba(255,255,255,.15);color:#fff;width:auto;">
                        ${pinOptions}
                    </select>
                </div>
            </div>
            <button class="route-stop-remove" onclick="window.removeRouteStop(${idx})" title="Remove">✕</button>
        `;
        list.appendChild(el);
    });
};

window.generateRoute = function () {
    if (window.routeStops.length === 0) return;

    const doGenerate = (userLat, userLng) => {
        const optimized = optimizeRoute(window.routeStops, userLat, userLng);

        let url = `https://www.google.com/maps/dir/?api=1`;
        if (optimized.length === 1) {
            url += `&destination=${optimized[0].lat},${optimized[0].lng}`;
        } else {
            const dest = optimized[optimized.length - 1];
            url += `&destination=${dest.lat},${dest.lng}`;
            const waypoints = optimized.slice(0, -1).map(s => `${s.lat},${s.lng}`).join('|');
            url += `&waypoints=${waypoints}`;
        }
        window.open(url, '_blank');
    };

    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            pos => doGenerate(pos.coords.latitude, pos.coords.longitude),
            () => doGenerate(window.routeStops[0].lat, window.routeStops[0].lng) // fallback: start from first stop
        );
    } else {
        doGenerate(window.routeStops[0].lat, window.routeStops[0].lng);
    }
};

// Make initMap globally available for the Google Maps callback
window.initMap = initMap;

document.addEventListener('DOMContentLoaded', () => {
    // The script is loaded by the map.html template automatically,
    // which then calls window.initMap.
    // If maps api is already loaded, initialize manually
    if (window.google && window.google.maps) {
        initMap();
    }
});

// Sync a single record directly from the marker popup
window.syncSingleRecord = async function(moduleName, recordId, btnElement) {
    const originalText = btnElement.innerHTML;
    btnElement.disabled = true;
    btnElement.innerHTML = '<span class="pulse-dot" style="margin:0;width:6px;height:6px;"></span> Syncing...';
    try {
        const res = await fetch(`/api/sync-record/${moduleName}/${recordId}`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            btnElement.style.color = '#10b981';
            btnElement.innerHTML = '✓ Synced!';
            setTimeout(() => {
                if (window.activeInfoWindow) window.activeInfoWindow.close();
                // Refresh map + list
                if (window.fetchData) window.fetchData();
            }, 1200);
        } else {
            btnElement.style.color = '#ef4444';
            btnElement.innerHTML = '✗ Failed';
            setTimeout(() => { btnElement.disabled = false; btnElement.innerHTML = originalText; btnElement.style.color = ''; }, 2500);
        }
    } catch(e) {
        btnElement.style.color = '#ef4444';
        btnElement.innerHTML = '✗ Error';
        setTimeout(() => { btnElement.disabled = false; btnElement.innerHTML = originalText; btnElement.style.color = ''; }, 2500);
    }
};

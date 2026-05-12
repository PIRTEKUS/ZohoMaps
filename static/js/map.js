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

    // Setup Search Button
    const searchBtn = document.getElementById('search-area-btn');

    // Show button when map is panned/zoomed
    map.addListener('dragend', () => { searchBtn.style.display = 'block'; });
    map.addListener('zoom_changed', () => { searchBtn.style.display = 'block'; });

    searchBtn.addEventListener('click', () => {
        searchBtn.style.display = 'none';
        loadMapData();
    });

    // Try HTML5 geolocation
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (position) => {
                const pos = {
                    lat: position.coords.latitude,
                    lng: position.coords.longitude,
                };
                map.setCenter(pos);
                map.setZoom(8); // Approx 200 miles across
                google.maps.event.addListenerOnce(map, 'idle', loadMapData);
            },
            () => {
                // Browser geolocation failed or denied, try IP-based fallback
                tryIPFallback();
            },
            { enableHighAccuracy: true, timeout: 5000, maximumAge: 0 }
        );
    } else {
        tryIPFallback();
    }
}

async function tryIPFallback() {
    try {
        console.log("Browser geolocation failed. Attempting IP-based location fallback...");
        const res = await fetch('https://ipapi.co/json/');
        const data = await res.json();
        if (data.latitude && data.longitude) {
            const pos = { lat: data.latitude, lng: data.longitude };
            map.setCenter(pos);
            map.setZoom(8);
            console.log("IP-based location success:", pos);
        }
    } catch (e) {
        console.error("IP-based fallback failed:", e);
    } finally {
        // Load data regardless of success
        google.maps.event.addListenerOnce(map, 'idle', loadMapData);
    }
}

async function loadMapData() {
    document.getElementById('legend-stats').innerHTML = `<span class="pulse-dot"></span> Loading area data...`;

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

        document.getElementById('legend-stats').innerHTML = `<span style="color:var(--success)">${data.length} records in area</span>`;

        plotData(data);
        updateLegend(data);
    } catch (e) {
        console.error(e);
        document.getElementById('legend-stats').innerHTML = `<span style="color:var(--error)">Error loading data</span>`;
    }
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
    
    // Reuse a single InfoWindow so only one popup is open at a time
    if (!window.activeInfoWindow) {
        window.activeInfoWindow = new google.maps.InfoWindow();
    }
    
    // Filter visible data first
    const visibleData = data.filter(item => !(window.hiddenModules && window.hiddenModules.has(item.module)));
    
    if (visibleData.length >= 1000) {
        document.getElementById('legend-stats').innerHTML += ` <span style="color:var(--warning);font-size:0.75rem;">(Limit reached, zoom in for more)</span>`;
    }

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
            let content = `<div class="info-window"><h3>${item.name}</h3><p><strong>Module:</strong> ${item.module}</p><div class="info-details">`;
            for (let [k, v] of Object.entries(item.record_data)) {
                if (v) content += `<div><strong>${k}:</strong> ${v}</div>`;
            }

            // Add route action buttons — onclick handlers also close the info window
            const safeName = item.name.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
            
            // Detect if user is on a mobile device for the "Open in App" link
            const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
            // Zoho CRM mobile deep link scheme: zohocrm://crm/[module]/[id]
            const zohoAppLink = `zohocrm://crm/${encodeURIComponent(item.module)}/${item.id}`;
            
            content += `<div class="info-actions" style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px;">
                <button class="btn-primary" style="font-size: 0.7rem; padding: 0.25rem;" onclick="activeInfoWindow.close(); window.getDirections(${item.lat}, ${item.lng})">Directions</button>
                <button class="btn-secondary" style="font-size: 0.7rem; padding: 0.25rem; color: #1e293b;" onclick="activeInfoWindow.close(); window.addToRoute('${item.id}', '${safeName}', ${item.lat}, ${item.lng})">Add to Route</button>
                <button class="btn-secondary" style="font-size: 0.7rem; padding: 0.25rem; grid-column: span 2; color: #1e293b;" onclick="activeInfoWindow.close(); window.open('${item.zoho_link}', '_blank')">Open in Zoho CRM (Web)</button>
                ${isMobile ? `<button class="btn-primary" style="font-size: 0.7rem; padding: 0.25rem; grid-column: span 2;" onclick="activeInfoWindow.close(); window.location.href='${zohoAppLink}'">Open in Zoho CRM App</button>` : ''}
            </div>`;

            content += `</div></div>`;

            window.activeInfoWindow.setContent(content);
            window.activeInfoWindow.open(map, marker);
        });

        markers.push(marker);
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

window.hiddenModules = window.hiddenModules || new Set();

function updateLegend(data) {
    const legend = document.getElementById('legend-container');
    legend.innerHTML = '';

    // Count visible records per module
    const moduleCounts = {};
    data.forEach(item => {
        moduleCounts[item.module] = (moduleCounts[item.module] || 0) + 1;
    });

    // Ensure window.configuredModules exists, or fallback to the data we have
    let configuredModules = window.configuredModules || [];
    
    // Build a color/icon lookup that matches BOTH the api_name AND the display label
    // (item.module from the server is already the display label/plural_label)
    const moduleColorByLabel = {};
    for (let cfg of configuredModules) {
        // Map api_name key
        moduleColorByLabel[cfg.module_name] = cfg.marker_color;
        // Also map the display label if stored
        if (cfg.module_label) moduleColorByLabel[cfg.module_label] = cfg.marker_color;
    }
    // Also pick colors from the actual data (stored in record color)
    data.forEach(item => {
        if (item.color && !moduleColorByLabel[item.module]) {
            moduleColorByLabel[item.module] = item.color;
        }
    });

    if (configuredModules.length === 0) {
        configuredModules = Object.keys(moduleCounts).map(mod => ({
            module_name: mod, 
            marker_color: moduleColorByLabel[mod] || '#4f46e5'
        }));
    }

    // Eye icon toggle instead of checkbox, plus Sync buttons
    for (let config of configuredModules) {
        const mod = config.module_name;
        // Color: use config setting, then fall back to what's in the data
        const color = config.marker_color || moduleColorByLabel[mod] || '#4f46e5';
        // Count: check both api_name and display label
        const count = moduleCounts[mod] || moduleCounts[config.module_label] || 0;

        
        const item = document.createElement('div');
        item.className = 'legend-item';
        
        const isVisible = !(window.hiddenModules && window.hiddenModules.has(mod));
        const eyeVisible = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
        const eyeHidden = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;
        const safeModule = mod.replace(/'/g, "\\'");
        
        item.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px; flex-grow: 1;">
                <button class="legend-eye-btn ${isVisible ? 'visible' : 'hidden'}" 
                        id="eye-${mod.replace(/[^a-z0-9]/gi,'_')}"
                        onclick="window.toggleModuleVisibility('${safeModule}', ${isVisible})"
                        title="${isVisible ? 'Hide' : 'Show'} ${mod}">
                    ${isVisible ? eyeVisible : eyeHidden}
                </button>
                <span class="color-dot" style="background-color: ${color}"></span>
                <span class="legend-name" style="flex-grow: 1;">${mod} <span class="legend-count" style="margin-left: 4px;">(${count})</span></span>
                <button class="btn-primary sync-mod-btn" onclick="syncSingleModule('${safeModule}', this)" style="padding: 2px 6px; font-size: 0.75rem; border-radius: 4px;" title="Sync ${mod} Data">Sync</button>
            </div>
        `;
        legend.appendChild(item);
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
    // New tab-based HTML uses #panel-route, #route-stops-list, #route-stats
    const routePanel = document.getElementById('panel-route');
    const list       = document.getElementById('route-stops-list');
    const stats      = document.getElementById('route-stats');

    // Update tab badge (works on both desktop and mobile)
    if (typeof window.updateRouteBadge === 'function') {
        window.updateRouteBadge(window.routeStops.length);
    }

    if (window.routeStops.length === 0) {
        // Nothing to show — switch back to legend tab on mobile
        if (routePanel) routePanel.style.display = 'none';
        return;
    }

    stats.textContent = `${window.routeStops.length} stop${window.routeStops.length === 1 ? '' : 's'} (Max 10) — will auto-optimize`;


    list.innerHTML = '';
    window.routeStops.forEach((stop, idx) => {
        const el = document.createElement('div');
        el.className = 'route-stop-item';

        // Build pin options
        let pinOptions = `<option value="">Auto</option>`;
        for (let p = 1; p <= window.routeStops.length; p++) {
            pinOptions += `<option value="${p}" ${stop.pinnedPos === p ? 'selected' : ''}>Stop #${p}</option>`;
        }

        el.innerHTML = `
            <div class="route-stop-name" title="${stop.name}">
                <span style="color:var(--primary);font-weight:600;">${idx + 1}.</span> ${stop.name}
                <div style="margin-top:4px;">
                    <label style="font-size:0.7rem;color:#94a3b8;">Force position: </label>
                    <select class="pin-select" onchange="window.setPinnedPos(${idx}, this.value)"
                        style="font-size:0.72rem;padding:1px 4px;border-radius:4px;background:rgba(15,23,42,0.8);border:1px solid rgba(255,255,255,0.15);color:#fff;width:auto;">
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

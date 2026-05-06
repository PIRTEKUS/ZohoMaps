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
                map.setZoom(12);
                // Load data for the device's local area once centered
                google.maps.event.addListenerOnce(map, 'idle', loadMapData);
            },
            () => {
                // Geolocation failed or denied, load data for default view
                google.maps.event.addListenerOnce(map, 'idle', loadMapData);
            }
        );
    } else {
        // Browser doesn't support Geolocation
        google.maps.event.addListenerOnce(map, 'idle', loadMapData);
    }
}

async function loadMapData() {
    document.getElementById('legend-stats').innerHTML = `<span class="pulse-dot"></span> Loading area data...`;

    try {
        const bounds = map.getBounds();
        const ne = bounds.getNorthEast();
        const sw = bounds.getSouthWest();

        const params = new URLSearchParams({
            min_lat: sw.lat(),
            max_lat: ne.lat(),
            min_lng: sw.lng(),
            max_lng: ne.lng()
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

function plotData(data) {
    // Clear existing markers
    markers.forEach(m => m.setMap(null));
    markers = [];
    if (markerCluster) {
        markerCluster.clearMarkers();
    }

    const bounds = new google.maps.LatLngBounds();
    const infoWindow = new google.maps.InfoWindow();
    
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

            // Add route action buttons
            const safeName = item.name.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
            content += `<div class="info-actions" style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px;">
                <button class="btn-primary" style="font-size: 0.7rem; padding: 0.25rem;" onclick="window.getDirections(${item.lat}, ${item.lng})">Directions</button>
                <button class="btn-secondary" style="font-size: 0.7rem; padding: 0.25rem; color: #1e293b;" onclick="window.addToRoute('${item.id}', '${safeName}', ${item.lat}, ${item.lng})">Add to Route</button>
                <button class="btn-secondary" style="font-size: 0.7rem; padding: 0.25rem; grid-column: span 2; color: #1e293b;" onclick="window.open('${item.zoho_link}', '_blank')">Open in Zoho CRM</button>
            </div>`;

            content += `</div></div>`;

            infoWindow.setContent(content);
            infoWindow.open(map, marker);
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
                // console.log("Cluster clicked, zoom prevented.");
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

    // Group by module
    const modules = {};
    data.forEach(item => {
        if (!modules[item.module]) {
            modules[item.module] = { count: 0, color: item.color };
        }
        modules[item.module].count++;
    });

    for (let [mod, info] of Object.entries(modules)) {
        const item = document.createElement('div');
        item.className = 'legend-item';
        const isChecked = !window.hiddenModules.has(mod);
        item.innerHTML = `
            <input type="checkbox" class="module-toggle" ${isChecked ? 'checked' : ''} 
                   onchange="window.toggleModuleVisibility('${mod}', this.checked)"
                   style="margin-right: 10px; cursor: pointer;">
            <span class="color-dot" style="background-color: ${info.color}"></span>
            <span class="legend-name">${mod}</span>
            <span class="legend-count">${info.count}</span>
        `;
        legend.appendChild(item);
    }
}

window.toggleModuleVisibility = function(moduleName, visible) {
    if (visible) {
        window.hiddenModules.delete(moduleName);
    } else {
        window.hiddenModules.add(moduleName);
    }
    // Re-plot data to apply visibility changes
    if (window.lastMapData) {
        plotData(window.lastMapData);
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
    const container = document.getElementById('route-planner-container');
    const list = document.getElementById('route-stops-list');
    const stats = document.getElementById('route-stats');

    if (window.routeStops.length === 0) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';
    container.style.flexDirection = 'column';
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

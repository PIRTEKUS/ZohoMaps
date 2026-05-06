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
            if(res.status === 401) window.location.href = '/login';
            throw new Error('Failed to fetch data');
        }
        const data = await res.json();
        
        document.getElementById('legend-stats').innerHTML = `<span style="color:var(--success)">${data.length} records in area</span>`;
        
        plotData(data);
        updateLegend(data);
    } catch(e) {
        console.error(e);
        document.getElementById('legend-stats').innerHTML = `<span style="color:var(--error)">Error loading data</span>`;
    }
}

function plotData(data) {
    // Clear existing markers
    markers.forEach(m => m.setMap(null));
    markers = [];

    const bounds = new google.maps.LatLngBounds();
    const infoWindow = new google.maps.InfoWindow();

    data.forEach(item => {
        const position = { lat: item.lat, lng: item.lng };
        
        // Custom SVG Marker to use the dynamically configured color
        const svgMarker = {
            path: "M10.453 14.016l6.563-6.609-1.406-1.406-5.156 5.203-2.063-2.109-1.406 1.406zM12 2.016q2.906 0 4.945 2.039t2.039 4.945q0 1.453-0.727 3.328t-1.758 3.516-2.039 3.070-1.711 2.273l-0.75 0.797q-0.281-0.328-0.75-0.867t-1.688-2.156-2.133-3.141-1.664-3.445-0.75-3.375q0-2.906 2.039-4.945t4.945-2.039z",
            fillColor: item.color || "#FF0000",
            fillOpacity: 0.9,
            strokeWeight: 1,
            strokeColor: "#FFFFFF",
            rotation: 0,
            scale: 2,
            anchor: new google.maps.Point(12, 24),
        };

        const marker = new google.maps.Marker({
            position: position,
            map: map,
            icon: svgMarker,
            title: item.name
        });

        bounds.extend(position);

        marker.addListener('click', () => {
            let content = `<div class="info-window"><h3>${item.name}</h3><p><strong>Module:</strong> ${item.module}</p><div class="info-details">`;
            for(let [k,v] of Object.entries(item.record_data)) {
                if(v) content += `<div><strong>${k}:</strong> ${v}</div>`;
            }
            
            // Add route action buttons
            const safeName = item.name.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
            content += `<div class="info-actions">
                <button class="btn-primary" style="font-size: 0.75rem; padding: 0.2rem 0.5rem;" onclick="window.getDirections(${item.lat}, ${item.lng})">Directions</button>
                <button class="btn-secondary" style="font-size: 0.75rem; padding: 0.2rem 0.5rem; color: #1e293b;" onclick="window.addToRoute('${item.id}', '${safeName}', ${item.lat}, ${item.lng})">Add to Route</button>
            </div>`;
            
            content += `</div></div>`;
            
            infoWindow.setContent(content);
            infoWindow.open(map, marker);
        });

        markers.push(marker);
    });

    if (data.length > 0) {
        // Do not auto-fit bounds because we want the user to maintain their viewport
        // when searching an area.
    }
}

function updateLegend(data) {
    const legend = document.getElementById('legend-container');
    legend.innerHTML = '';
    
    // Group by module
    const modules = {};
    data.forEach(item => {
        if(!modules[item.module]) {
            modules[item.module] = { count: 0, color: item.color };
        }
        modules[item.module].count++;
    });

    for(let [mod, info] of Object.entries(modules)) {
        const item = document.createElement('div');
        item.className = 'legend-item';
        item.innerHTML = `
            <span class="color-dot" style="background-color: ${info.color}"></span>
            <span class="legend-name">${mod}</span>
            <span class="legend-count">${info.count}</span>
        `;
        legend.appendChild(item);
    }
}

// ROUTING LOGIC
window.routeStops = [];

window.getDirections = function(lat, lng) {
    const url = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
    window.open(url, '_blank');
};

window.addToRoute = function(id, name, lat, lng) {
    if (window.routeStops.length >= 10) {
        alert("Google Maps only supports a maximum of 10 stops per route.");
        return;
    }
    window.routeStops.push({ id, name, lat, lng });
    window.renderRoutePlanner();
};

window.removeRouteStop = function(index) {
    window.routeStops.splice(index, 1);
    window.renderRoutePlanner();
};

window.moveRouteStop = function(index, direction) {
    if (direction === -1 && index > 0) {
        const temp = window.routeStops[index];
        window.routeStops[index] = window.routeStops[index - 1];
        window.routeStops[index - 1] = temp;
    } else if (direction === 1 && index < window.routeStops.length - 1) {
        const temp = window.routeStops[index];
        window.routeStops[index] = window.routeStops[index + 1];
        window.routeStops[index + 1] = temp;
    }
    window.renderRoutePlanner();
};

window.renderRoutePlanner = function() {
    const container = document.getElementById('route-planner-container');
    const list = document.getElementById('route-stops-list');
    const stats = document.getElementById('route-stats');
    
    if (window.routeStops.length === 0) {
        container.style.display = 'none';
        return;
    }
    
    container.style.display = 'flex';
    container.style.flexDirection = 'column';
    stats.textContent = `${window.routeStops.length} stop${window.routeStops.length === 1 ? '' : 's'} (Max 10)`;
    
    list.innerHTML = '';
    window.routeStops.forEach((stop, idx) => {
        const el = document.createElement('div');
        el.className = 'route-stop-item';
        el.innerHTML = `
            <div class="route-stop-controls">
                <button class="route-btn-small" onclick="window.moveRouteStop(${idx}, -1)" ${idx === 0 ? 'style="visibility:hidden"' : ''}>▲</button>
                <button class="route-btn-small" onclick="window.moveRouteStop(${idx}, 1)" ${idx === window.routeStops.length - 1 ? 'style="visibility:hidden"' : ''}>▼</button>
            </div>
            <div class="route-stop-name" title="${stop.name}">
                <strong style="color:var(--primary)">${idx + 1}.</strong> ${stop.name}
            </div>
            <button class="route-stop-remove" onclick="window.removeRouteStop(${idx})" title="Remove">✕</button>
        `;
        list.appendChild(el);
    });
};

window.generateRoute = function() {
    if (window.routeStops.length === 0) return;
    
    let url = `https://www.google.com/maps/dir/?api=1`;
    
    if (window.routeStops.length === 1) {
        url += `&destination=${window.routeStops[0].lat},${window.routeStops[0].lng}`;
    } else {
        const dest = window.routeStops[window.routeStops.length - 1];
        url += `&destination=${dest.lat},${dest.lng}`;
        
        if (window.routeStops.length > 1) {
            const waypoints = window.routeStops.slice(0, -1).map(s => `${s.lat},${s.lng}`).join('|');
            url += `&waypoints=${waypoints}`;
        }
    }
    
    window.open(url, '_blank');
};

// Make initMap globally available for the Google Maps callback
window.initMap = initMap;

document.addEventListener('DOMContentLoaded', () => {
    // The script is loaded by the map.html template automatically,
    // which then calls window.initMap.
    // If maps api is already loaded, initialize manually
    if(window.google && window.google.maps) {
        initMap();
    }
});

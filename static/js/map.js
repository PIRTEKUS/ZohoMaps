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

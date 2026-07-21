let map;
let markers = [];
window.mapInitialized = false;
window.isProgrammaticMove = false;
let programmaticTimeout = null;

window.selectedFranchiseIds = new Set(['all']);
window.filterMapData = function(data) {
    if (!data) return [];
    if (!window.selectedFranchiseIds || window.selectedFranchiseIds.has('all')) {
        return data;
    }
    return data.filter(item => window.selectedFranchiseIds.has(String(item.franchise_id)));
};

window.toggleFranchiseDropdown = function(e) {
    e.stopPropagation();
    const menu = document.getElementById('franchise-dropdown-menu');
    const btn = document.getElementById('franchise-dropdown-btn');
    if (menu) {
        const isOpen = menu.classList.toggle('open');
        if (btn) btn.classList.toggle('open', isOpen);
    }
};

window.toggleFranchiseSelection = function(id, event) {
    if (event.target.tagName === 'INPUT') {
        event.stopPropagation();
    } else {
        event.preventDefault();
        event.stopPropagation();
    }

    const checkboxId = id === 'all' ? 'chk-all' : `chk-${id}`;
    const mCheckboxId = id === 'all' ? 'chk-m-all' : `chk-m-${id}`;
    
    const chk = document.getElementById(checkboxId);
    const chkM = document.getElementById(mCheckboxId);

    let newCheckedState;
    if (event.target.tagName === 'INPUT') {
        newCheckedState = event.target.checked;
    } else {
        newCheckedState = chk ? !chk.checked : (chkM ? !chkM.checked : false);
    }

    if (chk) chk.checked = newCheckedState;
    if (chkM) chkM.checked = newCheckedState;

    const list = window.configuredFranchises || [];
    
    if (id === 'all') {
        if (newCheckedState) {
            window.selectedFranchiseIds = new Set(['all']);
            list.forEach(f => {
                const c = document.getElementById(`chk-${f.id}`);
                const cm = document.getElementById(`chk-m-${f.id}`);
                if (c) c.checked = true;
                if (cm) cm.checked = true;
            });
        } else {
            window.selectedFranchiseIds = new Set();
            list.forEach(f => {
                const c = document.getElementById(`chk-${f.id}`);
                const cm = document.getElementById(`chk-m-${f.id}`);
                if (c) c.checked = false;
                if (cm) cm.checked = false;
            });
        }
    } else {
        if (newCheckedState) {
            if (window.selectedFranchiseIds.has('all')) {
                window.selectedFranchiseIds.delete('all');
            }
            window.selectedFranchiseIds.add(id);
        } else {
            window.selectedFranchiseIds.delete('all');
            window.selectedFranchiseIds.delete(id);
            const call = document.getElementById('chk-all');
            const callM = document.getElementById('chk-m-all');
            if (call) call.checked = false;
            if (callM) callM.checked = false;
        }

        let allChecked = true;
        list.forEach(f => {
            const c = document.getElementById(`chk-${f.id}`);
            if (c && !c.checked) allChecked = false;
        });

        if (allChecked && list.length > 0) {
            window.selectedFranchiseIds = new Set(['all']);
            const call = document.getElementById('chk-all');
            const callM = document.getElementById('chk-m-all');
            if (call) call.checked = true;
            if (callM) callM.checked = true;
        }
    }

    window.updateFranchiseFilterUI();
};

window.updateFranchiseFilterUI = function() {
    const list = window.configuredFranchises || [];
    const label = document.getElementById('franchise-filter-label');
    const mLabelCount = document.getElementById('mobile-franchise-count');
    
    let labelText = 'All Franchises';
    let mobileText = 'All';

    if (window.selectedFranchiseIds.has('all')) {
        labelText = 'All Franchises';
        mobileText = 'All';
    } else {
        const selectedList = list.filter(f => window.selectedFranchiseIds.has(f.id));
        if (selectedList.length === 0) {
            labelText = '0 Franchises';
            mobileText = '0';
        } else if (selectedList.length === 1) {
            labelText = selectedList[0].name;
            mobileText = '1';
        } else if (selectedList.length === list.length) {
            labelText = 'All Franchises';
            mobileText = 'All';
        } else {
            labelText = `${selectedList.length} Selected`;
            mobileText = String(selectedList.length);
        }
    }

    if (label) label.textContent = labelText;
    if (mLabelCount) mLabelCount.textContent = mobileText;

    if (typeof window.applyBoundaryStyles === 'function') {
        window.applyBoundaryStyles();
        
        if (window.selectedFranchiseIds && !window.selectedFranchiseIds.has('all') && window.selectedFranchiseIds.size === 1) {
            const selectedId = Array.from(window.selectedFranchiseIds)[0];
            if (window.franchiseBoundaries && window.franchiseBoundaries[selectedId]) {
                fitMapToBoundary(window.franchiseBoundaries[selectedId]);
            }
        }
    }

    if (window.lastMapData) {
        plotData(window.lastMapData);
        updateLegend(window.lastMapData);
        if (window.updateRecordList) window.updateRecordList(window.lastMapData);
    }
};

// Close dropdown on clicking outside
document.addEventListener('click', function(e) {
    const menu = document.getElementById('franchise-dropdown-menu');
    const btn = document.getElementById('franchise-dropdown-btn');
    if (menu && !menu.contains(e.target) && btn && !btn.contains(e.target)) {
        menu.classList.remove('open');
        btn.classList.remove('open');
    }
});

async function initMap() {
    // Default fallback to US
    let initialCenter = { lat: 39.8283, lng: -98.5795 };
    let initialZoom = 4;

    map = new google.maps.Map(document.getElementById("map"), {
        center: initialCenter,
        zoom: initialZoom,
        disableDefaultUI: true,
        zoomControl: true,
    });
    window.map = map;

    // Setup the map-click listener ONCE here to close any open info popup
    // Must be done after map is initialized, not inside plotData (which runs repeatedly)
    map.addListener('click', () => {
        if (window.activeInfoWindow) window.activeInfoWindow.close();
    });

    // Auto-trigger search in this area with 500ms debounce when map is panned/zoomed
    let searchDebounceTimeout = null;

    function triggerAutoSearch() {
        if (!window.mapInitialized) return;

        if (window.isProgrammaticMove) {
            // Keep extending the programmatic timeout while moving
            if (programmaticTimeout) {
                clearTimeout(programmaticTimeout);
            }
            programmaticTimeout = setTimeout(() => {
                window.isProgrammaticMove = false;
            }, 1000);
            return;
        }

        if (searchDebounceTimeout) {
            clearTimeout(searchDebounceTimeout);
        }

        // Show the search button immediately to give visual feedback that search is pending
        if (window.showSearchButton) window.showSearchButton();

        searchDebounceTimeout = setTimeout(() => {
            console.log('[Map] Auto-triggering search in this area...');
            if (typeof window.searchArea === 'function') {
                window.searchArea();
            } else if (window.fetchData) {
                const btn = document.getElementById('search-area-btn');
                if (btn) btn.style.display = 'none';
                window.fetchData();
            }
        }, 500);
    }

    map.addListener('dragend', triggerAutoSearch);
    map.addListener('zoom_changed', triggerAutoSearch);

    // Also keep direct click on the button (handled in map.html as searchArea())
    window.fetchData = loadMapData;
    // Check if target coordinates are provided for deep-linking
    if (window.targetLat !== null && window.targetLng !== null && !isNaN(window.targetLat) && !isNaN(window.targetLng)) {
        const targetPos = {
            lat: parseFloat(window.targetLat),
            lng: parseFloat(window.targetLng)
        };
        // Store for distance-sort in record list
        window.userLat = targetPos.lat;
        window.userLng = targetPos.lng;

        setTimeout(() => {
            google.maps.event.trigger(map, 'resize');
            map.setCenter(targetPos);
            map.setZoom(14);
            google.maps.event.addListenerOnce(map, 'idle', () => {
                loadMapData().then(() => {
                    if (window.targetRecordId) {
                        window.focusMapMarker(window.targetRecordId);
                    }
                });
            });
        }, 150);
    } else {
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
        renderFranchiseBoundaries();
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
        window.mapInitialized = true;
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
    if (window.filterMapData) data = window.filterMapData(data);
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

        let markerIconOption;
        const isCustomIcon = item.icon && (item.icon.startsWith('/static/') || item.icon.includes('/') || item.icon.includes('.'));

        if (isCustomIcon) {
            const sizeName = (item.field_mappings && item.field_mappings.custom_marker_size) || 'medium';
            let maxSize = parseInt(sizeName);
            if (isNaN(maxSize)) {
                if (sizeName === 'small') maxSize = 24;
                else if (sizeName === 'large') maxSize = 48;
                else if (sizeName === 'xlarge') maxSize = 100;
                else if (sizeName === 'jumbo') maxSize = 200;
                else maxSize = 36;
            }

            const aspect = parseFloat((item.field_mappings && item.field_mappings.custom_marker_aspect_ratio)) || 1.0;

            let w, h;
            if (aspect >= 1.0) {
                w = maxSize;
                h = maxSize / aspect;
            } else {
                h = maxSize;
                w = maxSize * aspect;
            }

            markerIconOption = {
                url: item.icon,
                scaledSize: new google.maps.Size(w, h),
                anchor: new google.maps.Point(w / 2, h)
            };
        } else {
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
            markerIconOption = svgMarker;
        }

        const marker = new google.maps.Marker({
            position: position,
            map: map,
            icon: markerIconOption,
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
        const config = window.clusterConfig || {
            b1_from: 2,
            b1_to: 10,
            b1_color: '#3b82f6',
            b2_to: 50,
            b2_color: '#f59e0b',
            b3_color: '#ef4444'
        };

        const customRenderer = {
            render: ({ count, position }, stats, map) => {
                let color = config.b3_color;
                let size = 56;
                let fontSize = 14;

                if (count <= config.b1_to) {
                    color = config.b1_color;
                    size = 40;
                    fontSize = 12;
                } else if (count <= config.b2_to) {
                    color = config.b2_color;
                    size = 48;
                    fontSize = 13;
                }

                const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><circle cx="${size/2}" cy="${size/2}" r="${size/2 - 2}" fill="${color}" fill-opacity="0.9" stroke="#ffffff" stroke-width="2"/></svg>`;

                return new google.maps.Marker({
                    label: {
                        text: String(count),
                        color: "white",
                        fontSize: fontSize + "px",
                        fontWeight: "bold"
                    },
                    position,
                    icon: {
                        url: 'data:image/svg+xml;base64,' + btoa(svg),
                        scaledSize: new google.maps.Size(size, size),
                        anchor: new google.maps.Point(size / 2, size / 2)
                    },
                    title: `Cluster of ${count} markers`,
                    zIndex: Number(google.maps.Marker.MAX_ZINDEX) + count
                });
            }
        };

        markerCluster = new markerClusterer.MarkerClusterer({ 
            markers, 
            map,
            algorithm: new markerClusterer.SuperClusterAlgorithm({
                minPoints: parseInt(config.b1_from) || 2
            }),
            renderer: customRenderer,
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

    let addHtml = '';
    if (item.field_mappings && Array.isArray(item.field_mappings.additional_field_labels) && item.field_mappings.additional_field_labels.length > 0) {
        const renderedLabels = new Set();
        item.field_mappings.additional_field_labels.forEach(label => {
            if (item.record_data[label] !== undefined && item.record_data[label] !== null && item.record_data[label] !== '') {
                addHtml += `<div style="margin-bottom:2px;"><strong>${label}:</strong> ${item.record_data[label]}</div>`;
                renderedLabels.add(label);
            }
        });
        // Render any remaining keys that are not address keys, don't start with '_', and weren't rendered yet
        const remainingKeys = Object.keys(item.record_data).filter(k => !addressKeys.includes(k) && !k.startsWith('_') && !renderedLabels.has(k)).sort();
        remainingKeys.forEach(k => {
            if (item.record_data[k] !== undefined && item.record_data[k] !== null && item.record_data[k] !== '') {
                addHtml += `<div style="margin-bottom:2px;"><strong>${k}:</strong> ${item.record_data[k]}</div>`;
            }
        });
    } else {
        const addKeys = Object.keys(item.record_data).filter(k => !addressKeys.includes(k) && !k.startsWith('_')).sort();
        addKeys.forEach(k => {
            if (item.record_data[k] !== undefined && item.record_data[k] !== null && item.record_data[k] !== '') {
                addHtml += `<div style="margin-bottom:2px;"><strong>${k}:</strong> ${item.record_data[k]}</div>`;
            }
        });
    }
    if (addHtml) content += `<div style="background:rgba(255,255,255,0.02);padding:8px;border-radius:6px;border:1px solid rgba(255,255,255,0.05);margin-bottom:12px;"><div style="font-size:0.75rem;color:#94a3b8;text-transform:uppercase;margin-bottom:4px;font-weight:600;">Additional Info</div>${addHtml}</div>`;

    const safeName = item.name.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    const zohoAppLink = `zohocrm://crm/${encodeURIComponent(item.api_module_name || item.module)}/${item.id}`;

    // Extract phone fields
    const phoneFields = [];
    Object.entries(item.record_data || {}).forEach(([key, val]) => {
        if (!addressKeys.includes(key) && !key.startsWith('_') && val) {
            const lowerKey = key.toLowerCase();
            if (lowerKey.includes('phone') || lowerKey.includes('mobile')) {
                phoneFields.push({ label: key, value: String(val).trim() });
            }
        }
    });

    const phoneFieldsJson = JSON.stringify(phoneFields).replace(/"/g, '&quot;');
    const callButtonHtml = phoneFields.length > 0 ? `
        <button class="btn-primary" style="font-size:0.7rem;padding:0.25rem;grid-column:span 2;background-color:#10b981;box-shadow: 0 4px 14px 0 rgba(16, 185, 129, 0.39);"
            onclick="window.activeInfoWindow&&window.activeInfoWindow.close();window.makePhoneCall('${safeName}', '${phoneFieldsJson}')">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:2px;vertical-align:middle;"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
            Call
        </button>
    ` : '';

    content += `<div class="info-actions" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;">
        ${callButtonHtml}
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

    window.isProgrammaticMove = true;
    if (programmaticTimeout) clearTimeout(programmaticTimeout);

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

        programmaticTimeout = setTimeout(() => {
            window.isProgrammaticMove = false;
        }, 1000);
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

            if (programmaticTimeout) clearTimeout(programmaticTimeout);
            programmaticTimeout = setTimeout(() => {
                window.isProgrammaticMove = false;
            }, 1000);
        });
    } else {
        console.error('[focusMapMarker] record not found anywhere. id=', sid);
        window.isProgrammaticMove = false;
    }
};


function updateLegend(data) {
    if (window.filterMapData) data = window.filterMapData(data);
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
        const apiName = config.module_name;

        // Resolve display label = what item.module holds in server data (must match for the filter to work)
        // Try: exact api_name key, then module_label, then fuzzy match (underscore vs space)
        const displayLabel = moduleCounts[apiName] !== undefined
            ? apiName
            : (config.module_label && moduleCounts[config.module_label] !== undefined
                ? config.module_label
                : (Object.keys(moduleCounts).find(k =>
                    k.replace(/[_\s]/g, '').toLowerCase() ===
                    apiName.replace(/[_\s]/g, '').toLowerCase()
                  ) || apiName));

        const color       = config.marker_color || moduleColorByLabel[displayLabel] || moduleColorByLabel[apiName] || '#4f46e5';
        const count       = moduleCounts[displayLabel] || 0;
        // Store displayLabel in hiddenModules so plotData filter matches item.module
        const isVisible   = !(window.hiddenModules && window.hiddenModules.has(displayLabel));
        const safeLabel   = displayLabel.replace(/'/g, "\\'");
        const safeApiName = apiName.replace(/'/g, "\\'");

        const row = document.createElement('div');
        row.className = 'cat-row';
        row.innerHTML = `
            <span class="cat-dot" style="background:${color};"></span>
            <span class="cat-label">${displayLabel}</span>
            <span class="cat-count">${count}</span>
            <button class="cat-eye" id="eye-${displayLabel.replace(/[^a-z0-9]/gi,'_')}"
                    onclick="window.toggleModuleVisibility('${safeLabel}', ${isVisible})" title="${isVisible ? 'Hide' : 'Show'} ${displayLabel}">
                ${isVisible ? eyeVisible : eyeHidden}
            </button>
            <button class="cat-sync" onclick="syncSingleModule('${safeApiName}', this)">Sync</button>
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

window.hiddenModules = window.hiddenModules || new Set();

window.toggleModuleVisibility = function(moduleName, makeHidden) {
    if (!window.hiddenModules) window.hiddenModules = new Set();
    if (makeHidden) {
        window.hiddenModules.add(moduleName);
    } else {
        window.hiddenModules.delete(moduleName);
    }
    if (window.lastMapData) {
        plotData(window.lastMapData);
        updateLegend(window.lastMapData);
        // Pass only the visible records to the list
        const visibleForList = window.lastMapData.filter(
            item => !window.hiddenModules.has(item.module)
        );
        if (window.updateRecordList) window.updateRecordList(visibleForList);
    }
};

// ROUTING LOGIC
window.routeStops = []; // { id, name, lat, lng, pinnedPos: null | number }

window.getDirections = function (lat, lng) {
    const url = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
    window.open(url, '_blank');
};

window.addToRoute = function (id, name, lat, lng) {
    const maxStops = parseInt(window.routeMaxStops) || 10;
    if (window.routeStops.length >= maxStops) {
        alert(`You can only add up to ${maxStops} stops to a route.`);
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
            btnElement.innerHTML = data.hidden ? 'Removed!' : '✓ Synced!';
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

// ── Franchise Territory Boundaries rendering & controls ───────────────────────────
window.boundaryLabels = [];

window.applyBoundaryStyles = function(hideOverride) {
    if (!window.map || !window.map.data) return;
    const hide = (typeof hideOverride === 'boolean') ? hideOverride : (window.boundariesHidden || false);
    const config = window.boundaryStyleConfig || {
        color: '#6366f1',
        fillOpacity: 0.05,
        strokeWeight: 2,
        showLabels: true,
        labelSize: 14,
        labelColor: '#ffffff'
    };
    
    // 1. Update the Data layer styles
    window.map.data.setStyle(feature => {
        if (hide) {
            return { visible: false };
        }
        
        const franchiseId = feature.getId();
        let color = config.color || '#6366f1';
        let isHighlighted = false;
        let visible = true;
        
        if (window.selectedFranchiseIds && !window.selectedFranchiseIds.has('all')) {
            if (window.selectedFranchiseIds.has(franchiseId)) {
                isHighlighted = true;
                color = '#10b981'; // Always highlight selection in vibrant green
            } else {
                visible = false; // Hide non-selected franchise boundaries
            }
        }
        
        return {
            strokeColor: color,
            strokeOpacity: isHighlighted ? 0.95 : 0.65,
            strokeWeight: isHighlighted ? Math.max(4, config.strokeWeight + 2) : config.strokeWeight,
            fillColor: color,
            fillOpacity: isHighlighted ? Math.max(0.15, config.fillOpacity + 0.05) : config.fillOpacity,
            visible: visible,
            clickable: true
        };
    });

    // 2. Update centered text label visibility & style dynamically
    if (window.boundaryLabels) {
        window.boundaryLabels.forEach(lbl => {
            if (hide) {
                lbl.setMap(null);
            } else {
                const showL = config.showLabels;
                if (!showL) {
                    lbl.setMap(null);
                    return;
                }
                
                const franchiseId = lbl.franchiseId;
                let labelVisible = true;
                if (window.selectedFranchiseIds && !window.selectedFranchiseIds.has('all')) {
                    if (!window.selectedFranchiseIds.has(franchiseId)) {
                        labelVisible = false;
                    }
                }
                lbl.setMap(labelVisible ? window.map : null);
            }
        });
    }
};

function getPolygonCentroid(coordinates, type) {
    let sumLat = 0;
    let sumLng = 0;
    let count = 0;
    
    const processRing = (ring) => {
        ring.forEach(pt => {
            sumLng += pt[0];
            sumLat += pt[1];
            count++;
        });
    };
    
    if (type === 'Polygon') {
        if (coordinates && coordinates[0]) {
            processRing(coordinates[0]); // Outer boundary ring only
        }
    } else if (type === 'MultiPolygon') {
        if (coordinates) {
            coordinates.forEach(poly => {
                if (poly && poly[0]) {
                    processRing(poly[0]);
                }
            });
        }
    }
    
    if (count === 0) return null;
    return { lat: sumLat / count, lng: sumLng / count };
}

function renderFranchiseBoundaries() {
    if (!window.franchiseBoundaries || Object.keys(window.franchiseBoundaries).length === 0) return;
    
    const config = window.boundaryStyleConfig || {};
    const features = [];
    
    // Clear any existing labels first
    if (window.boundaryLabels) {
        window.boundaryLabels.forEach(lbl => lbl.setMap(null));
        window.boundaryLabels = [];
    }

    Object.entries(window.franchiseBoundaries).forEach(([id, boundary]) => {
        features.push({
            type: 'Feature',
            id: id,
            geometry: {
                type: boundary.type,
                coordinates: boundary.coordinates
            },
            properties: {
                name: boundary.name,
                franchiseId: id
            }
        });

        // Add centered name label marker overlay
        const centroid = getPolygonCentroid(boundary.coordinates, boundary.type);
        if (centroid) {
            const lbl = new google.maps.Marker({
                position: centroid,
                map: window.map,
                icon: {
                    path: google.maps.SymbolPath.CIRCLE,
                    scale: 0 // Invisible symbol icon
                },
                label: {
                    text: boundary.name,
                    color: config.labelColor || '#ffffff',
                    fontSize: (config.labelSize || 14) + 'px',
                    fontWeight: 'bold'
                }
            });
            lbl.franchiseId = id;
            window.boundaryLabels.push(lbl);
        }
    });
    
    const featureCollection = {
        type: 'FeatureCollection',
        features: features
    };
    
    window.map.data.addGeoJson(featureCollection);
    window.applyBoundaryStyles();
    
    // Info Window tooltip on territory click
    const boundaryInfoWindow = new google.maps.InfoWindow();
    window.map.data.addListener('click', event => {
        const name = event.feature.getProperty('name');
        boundaryInfoWindow.setContent(`
            <div style="padding: 0.5rem; color: #1e293b; font-family: inherit; font-size: 0.85rem; font-weight: 500;">
                🗺️ Territory: <strong style="color: var(--primary);">${name}</strong>
            </div>
        `);
        boundaryInfoWindow.setPosition(event.latLng);
        boundaryInfoWindow.open(window.map);
    });
}

function fitMapToBoundary(boundary) {
    if (!boundary || !boundary.coordinates) return;
    const bounds = new google.maps.LatLngBounds();
    
    const processRing = (ring) => {
        ring.forEach(pt => {
            bounds.extend(new google.maps.LatLng(pt[1], pt[0]));
        });
    };
    
    if (boundary.type === 'Polygon') {
        boundary.coordinates.forEach(processRing);
    } else if (boundary.type === 'MultiPolygon') {
        boundary.coordinates.forEach(poly => {
            poly.forEach(processRing);
        });
    }
    
    if (!bounds.isEmpty()) {
        window.isProgrammaticMove = true; // Prevents auto-search trigger
        window.map.fitBounds(bounds);
    }
}

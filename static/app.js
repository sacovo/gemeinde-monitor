// Application State
let communesList = [];
let enteredResults = [];
let projections = {};
let historicalVotesMeta = {};

// DOM Elements
const searchInput = document.getElementById('commune-search');
const selectedGeoIdInput = document.getElementById('selected-geo-id');
const autocompleteList = document.getElementById('autocomplete-list');
const yesVotesInput = document.getElementById('yes-votes');
const noVotesInput = document.getElementById('no-votes');
const eligibleVotersInput = document.getElementById('eligible-voters');
const submitBtn = document.getElementById('submit-btn');
const clearBtn = document.getElementById('clear-btn');
const resultForm = document.getElementById('result-form');

const baselineSelect = document.getElementById('baseline-select');
const compareSelect = document.getElementById('compare-select');

const gaugeProgress = document.getElementById('gauge-progress');
const projectionPercentage = document.getElementById('projection-percentage');
const projectionOutcome = document.getElementById('projection-outcome');

const statR2 = document.getElementById('stat-r2');
const statCount = document.getElementById('stat-count');
const statTurnout = document.getElementById('stat-turnout');
const statVotes = document.getElementById('stat-votes');

const paramSlopeYes = document.getElementById('param-slope-yes');
const paramInterceptYes = document.getElementById('param-intercept-yes');
const paramSlopePart = document.getElementById('param-slope-part');
const paramInterceptPart = document.getElementById('param-intercept-part');

const resultsTbody = document.getElementById('results-tbody');

// Initialize App
document.addEventListener('DOMContentLoaded', async () => {
    await fetchCommunes();
    await fetchResults();
    setupAutocomplete();
    setupEventListeners();
});

function populateSelectors() {
    // Keep the "Historical Average" option and add all other votes
    // We only populate once if options are empty besides the first one
    if (baselineSelect.options.length > 1) return;

    // Add Ridge Regression option
    const optRidge = document.createElement('option');
    optRidge.value = 'ridge';
    optRidge.textContent = 'Dynamic Weighted (Ridge Regression)';
    baselineSelect.appendChild(optRidge);

    const optRidge2 = document.createElement('option');
    optRidge2.value = 'ridge';
    optRidge2.textContent = 'Dynamic Weighted (Ridge)';
    compareSelect.appendChild(optRidge2);

    Object.entries(historicalVotesMeta).forEach(([voteId, meta]) => {
        const title = `${meta.title} (${meta.year})`;
        
        // Add to baseline selection
        const opt1 = document.createElement('option');
        opt1.value = voteId;
        opt1.textContent = title;
        baselineSelect.appendChild(opt1);

        // Add to compare selection
        const opt2 = document.createElement('option');
        opt2.value = voteId;
        opt2.textContent = title;
        compareSelect.appendChild(opt2);
    });
}

// Fetch Master List of Communes
async function fetchCommunes() {
    try {
        const res = await fetch('/api/communes');
        if (!res.ok) throw new Error('Failed to fetch communes');
        communesList = await res.json();
    } catch (err) {
        console.error('Error fetching communes:', err);
    }
}

// Fetch Results and Projections
async function fetchResults() {
    try {
        const res = await fetch('/api/results');
        if (!res.ok) throw new Error('Failed to fetch results');
        const data = await res.json();
        
        enteredResults = data.entered_results;
        projections = data.projections;
        historicalVotesMeta = data.historical_votes_meta;
        
        populateSelectors();
        renderDashboard();
    } catch (err) {
        console.error('Error fetching results:', err);
    }
}

// Render Dashboard UI
function renderDashboard() {
    renderProjection();
    renderResultsTable();
}

// Render Projection Gauge and Statistics
function renderProjection() {
    const selectedBaseline = baselineSelect.value;
    const proj = projections[selectedBaseline];
    
    if (!proj) return;
    
    const yesPct = proj.projected_yes_pct;
    const yesPctFormatted = (yesPct * 100).toFixed(1) + '%';
    
    projectionPercentage.textContent = yesPctFormatted;
    
    // Set Outcome text and styling
    if (proj.num_entered_communes === 0) {
        projectionOutcome.textContent = "Awaiting Data";
        projectionOutcome.className = "outcome-badge";
        gaugeProgress.className.baseVal = "gauge-progress";
        
        // Clear gauge progress
        setGaugeProgress(0);
    } else {
        const isPass = yesPct >= 0.50;
        projectionOutcome.textContent = isPass ? "Passing" : "Failing";
        projectionOutcome.className = `outcome-badge ${isPass ? 'passing' : 'failing'}`;
        gaugeProgress.className.baseVal = `gauge-progress ${isPass ? 'passing' : 'failing'}`;
        
        // Update Gauge Ring (Circumference is ~534)
        setGaugeProgress(yesPct);
    }
    
    // Render Stats Grid
    const r2Val = proj.r_squared_yes;
    statR2.textContent = (r2Val !== null && r2Val !== undefined) ? r2Val.toFixed(3) : 'N/A';
    statCount.textContent = `${proj.num_entered_communes} / ${communesList.length}`;
    statTurnout.textContent = (proj.projected_participation * 100).toFixed(1) + '%';
    statVotes.textContent = proj.projected_total_votes.toLocaleString();
    
    // Render Equation Parameters
    const detailsContent = document.querySelector('.details-content');
    if (!detailsContent) return;
    
    if (selectedBaseline === 'ridge') {
        let yesEqHtml = `<strong>Yes % weights:</strong><br>`;
        let partEqHtml = `<strong>Turnout weights:</strong><br>`;
        
        if (proj.weights_yes && proj.weights_part && proj.num_entered_communes >= 2) {
            const voteIds = Object.keys(historicalVotesMeta);
            voteIds.forEach((voteId, index) => {
                const meta = historicalVotesMeta[voteId];
                const wYes = proj.weights_yes[index];
                const wPart = proj.weights_part[index];
                const yesSign = wYes >= 0 ? '+' : '';
                const partSign = wPart >= 0 ? '+' : '';
                yesEqHtml += `• ${meta.title} (${meta.year}): <code>${yesSign}${wYes.toFixed(4)}</code><br>`;
                partEqHtml += `• ${meta.title} (${meta.year}): <code>${partSign}${wPart.toFixed(4)}</code><br>`;
            });
            const interceptYesSign = proj.intercept_yes >= 0 ? '+' : '';
            const interceptPartSign = proj.intercept_part >= 0 ? '+' : '';
            yesEqHtml += `• Intercept: <code>${interceptYesSign}${proj.intercept_yes.toFixed(4)}</code>`;
            partEqHtml += `• Intercept: <code>${interceptPartSign}${proj.intercept_part.toFixed(4)}</code>`;
        } else {
            yesEqHtml += `<em>Awaiting results (need ≥2 communes) to compute weights...</em>`;
            partEqHtml += `<em>Awaiting results (need ≥2 communes) to compute weights...</em>`;
        }
        
        detailsContent.innerHTML = `<p>${yesEqHtml}</p><p style="margin-top:0.75rem; border-top:1px dashed rgba(255,255,255,0.1); padding-top:0.75rem;">${partEqHtml}</p>`;
    } else {
        // Restore standard 1D linear regression display
        detailsContent.innerHTML = `
            <p><strong>Yes % Model:</strong> y = <span id="param-slope-yes">--</span> * x + <span id="param-intercept-yes">--</span></p>
            <p><strong>Turnout Model:</strong> p = <span id="param-slope-part">--</span> * x + <span id="param-intercept-part">--</span></p>
        `;
        
        const slopeYesEl = document.getElementById('param-slope-yes');
        const interceptYesEl = document.getElementById('param-intercept-yes');
        const slopePartEl = document.getElementById('param-slope-part');
        const interceptPartEl = document.getElementById('param-intercept-part');
        
        if (slopeYesEl && interceptYesEl && slopePartEl && interceptPartEl) {
            slopeYesEl.textContent = proj.slope_yes ? proj.slope_yes.toFixed(4) : '--';
            interceptYesEl.textContent = proj.intercept_yes !== undefined ? ((proj.intercept_yes >= 0 ? '+ ' : '- ') + Math.abs(proj.intercept_yes).toFixed(4)) : '--';
            slopePartEl.textContent = proj.slope_part ? proj.slope_part.toFixed(4) : '--';
            interceptPartEl.textContent = proj.intercept_part !== undefined ? ((proj.intercept_part >= 0 ? '+ ' : '- ') + Math.abs(proj.intercept_part).toFixed(4)) : '--';
        }
    }
}

// SVG Gauge calculation: Circumference = 2 * pi * r = 2 * pi * 85 = 534.07
function setGaugeProgress(pct) {
    const circumference = 534.07;
    const offset = circumference - (pct * circumference);
    gaugeProgress.style.strokeDashoffset = offset;
}

// Render Table of Entered Commune Results
function renderResultsTable() {
    resultsTbody.innerHTML = '';
    
    if (enteredResults.length === 0) {
        resultsTbody.innerHTML = `
            <tr>
                <td colspan="9" class="empty-table-message">
                    <svg class="empty-icon" viewBox="0 0 24 24">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="12" y1="8" x2="12" y2="12"></line>
                        <line x1="12" y1="16" x2="12.01" y2="16"></line>
                    </svg>
                    <p>No communal results entered yet. Start entering results above.</p>
                </td>
            </tr>
        `;
        return;
    }
    
    const compareBaseline = compareSelect.value;
    
    enteredResults.forEach(res => {
        const tr = document.createElement('tr');
        
        // Formatted Percentages
        const yesPctVal = (res.yes_pct * 100).toFixed(2) + '%';
        const partPctVal = (res.participation_pct * 100).toFixed(2) + '%';
        
        // Calculate Delta vs selected historical baseline
        const comp = res.comparisons[compareBaseline];
        let deltaHtml = '--';
        if (comp) {
            const diffVal = comp.yes_pct_diff * 100;
            const sign = diffVal >= 0 ? '+' : '';
            const diffClass = diffVal > 0.05 ? 'better' : (diffVal < -0.05 ? 'worse' : 'neutral');
            const diffText = `${sign}${diffVal.toFixed(2)}%`;
            deltaHtml = `<span class="delta-tag ${diffClass}">${diffText}</span>`;
        }
        
        tr.innerHTML = `
            <td><code>${res.geo_id}</code></td>
            <td><strong>${res.name}</strong></td>
            <td><span class="canton-badge" title="${res.canton}">${res.canton_abbr}</span></td>
            <td>${res.eligible.toLocaleString()}</td>
            <td>
                <div class="raw-votes">
                    <span class="yes-count">${res.yes_votes.toLocaleString()}</span> / 
                    <span class="no-count">${res.no_votes.toLocaleString()}</span>
                </div>
            </td>
            <td><strong>${yesPctVal}</strong></td>
            <td>${partPctVal}</td>
            <td>${deltaHtml}</td>
            <td class="actions-col">
                <button type="button" class="btn-delete" data-id="${res.geo_id}" title="Remove this result">
                    <svg viewBox="0 0 24 24">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        <line x1="10" y1="11" x2="10" y2="17"></line>
                        <line x1="14" y1="11" x2="14" y2="17"></line>
                    </svg>
                </button>
            </td>
        `;
        
        resultsTbody.appendChild(tr);
    });
}

// Autocomplete Dropdown Setup
let currentFocus = -1;

function setupAutocomplete() {
    searchInput.addEventListener('input', function() {
        const val = this.value;
        closeAllLists();
        
        if (!val) return;
        currentFocus = -1;
        
        // Filter communes (by name, canton, or ZIP/ID)
        const valLower = val.toLowerCase();
        const matches = communesList.filter(c => 
            c.name.toLowerCase().includes(valLower) || 
            c.canton.toLowerCase().includes(valLower) ||
            c.canton_abbr.toLowerCase().includes(valLower) ||
            (c.name.toLowerCase() + " " + c.canton_abbr.toLowerCase()).includes(valLower) ||
            c.geo_id.toString().includes(valLower)
        ).slice(0, 10); // Limit to top 10 results
        
        if (matches.length === 0) {
            autocompleteList.classList.add('hidden');
            return;
        }
        
        autocompleteList.classList.remove('hidden');
        
        matches.forEach(match => {
            const div = document.createElement('div');
            div.className = 'autocomplete-item';
            div.innerHTML = `
                <span class="autocomplete-name">${match.name} (${match.canton_abbr})</span>
                <span class="autocomplete-meta">BFS: ${match.geo_id}</span>
            `;
            
            div.addEventListener('click', () => {
                selectCommune(match);
            });
            
            autocompleteList.appendChild(div);
        });
    });
    
    // Keyboard navigation in autocomplete list
    searchInput.addEventListener('keydown', function(e) {
        let list = autocompleteList;
        if (list) list = list.getElementsByTagName('div');
        if (e.keyCode === 40) { // Down key
            currentFocus++;
            addActive(list);
        } else if (e.keyCode === 38) { // Up key
            currentFocus--;
            addActive(list);
        } else if (e.keyCode === 13) { // Enter key
            e.preventDefault();
            if (currentFocus > -1) {
                if (list) list[currentFocus].click();
            }
        }
    });
    
    // Close lists when clicking outside
    document.addEventListener('click', (e) => {
        if (e.target !== searchInput && e.target !== autocompleteList) {
            closeAllLists();
        }
    });
}

function addActive(x) {
    if (!x) return false;
    removeActive(x);
    if (currentFocus >= x.length) currentFocus = 0;
    if (currentFocus < 0) currentFocus = (x.length - 1);
    x[currentFocus].classList.add('active');
    x[currentFocus].scrollIntoView({ block: 'nearest' });
}

function removeActive(x) {
    for (let i = 0; i < x.length; i++) {
        x[i].classList.remove('active');
    }
}

function closeAllLists() {
    autocompleteList.innerHTML = '';
    autocompleteList.classList.add('hidden');
}

// Select Commune from search list
function selectCommune(commune) {
    searchInput.value = `${commune.name} (${commune.canton_abbr})`;
    selectedGeoIdInput.value = commune.geo_id;
    
    // Fill in default eligible voters
    eligibleVotersInput.value = commune.eligible;
    
    // Enable inputs
    yesVotesInput.disabled = false;
    noVotesInput.disabled = false;
    eligibleVotersInput.disabled = false;
    submitBtn.disabled = false;
    
    // Check if result already exists for this commune to preload values
    const existing = enteredResults.find(r => r.geo_id === commune.geo_id);
    if (existing) {
        yesVotesInput.value = existing.yes_votes;
        noVotesInput.value = existing.no_votes;
        eligibleVotersInput.value = existing.eligible;
        submitBtn.textContent = 'Update Result';
    } else {
        yesVotesInput.value = '';
        noVotesInput.value = '';
        submitBtn.textContent = 'Add Result';
    }
    
    closeAllLists();
    yesVotesInput.focus();
}

// Clear/Reset Form State
function resetForm() {
    searchInput.value = '';
    selectedGeoIdInput.value = '';
    yesVotesInput.value = '';
    noVotesInput.value = '';
    eligibleVotersInput.value = '';
    
    yesVotesInput.disabled = true;
    noVotesInput.disabled = true;
    eligibleVotersInput.disabled = true;
    submitBtn.disabled = true;
    submitBtn.textContent = 'Add Result';
}

// Event Listeners Setup
function setupEventListeners() {
    // Form Submit Event
    resultForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const geoId = parseInt(selectedGeoIdInput.value);
        const yesVotes = parseInt(yesVotesInput.value);
        const noVotes = parseInt(noVotesInput.value);
        const eligible = parseInt(eligibleVotersInput.value);
        
        if (isNaN(geoId) || isNaN(yesVotes) || isNaN(noVotes) || isNaN(eligible)) {
            alert('Please fill out all fields with valid numbers.');
            return;
        }
        
        try {
            const res = await fetch('/api/results', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    geo_id: geoId,
                    yes_votes: yesVotes,
                    no_votes: noVotes,
                    eligible: eligible
                })
            });
            
            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || 'Failed to submit result');
            }
            
            const data = await res.json();
            enteredResults = data.entered_results;
            projections = data.projections;
            
            renderDashboard();
            resetForm();
            searchInput.focus();
        } catch (err) {
            console.error('Error submitting result:', err);
            alert(`Error: ${err.message}`);
        }
    });
    
    // Form Clear Button Event
    clearBtn.addEventListener('click', () => {
        resetForm();
    });
    
    // Select Dropdown Events
    baselineSelect.addEventListener('change', () => {
        renderProjection();
    });
    
    compareSelect.addEventListener('change', () => {
        renderResultsTable();
    });
    
    // Table Action Button Click (Delete)
    resultsTbody.addEventListener('click', async (e) => {
        // Find if click target or its parent is the delete button
        const deleteBtn = e.target.closest('.btn-delete');
        if (!deleteBtn) return;
        
        const geoId = parseInt(deleteBtn.getAttribute('data-id'));
        if (isNaN(geoId)) return;
        
        if (confirm('Are you sure you want to remove the result for this commune?')) {
            try {
                const res = await fetch(`/api/results/${geoId}`, {
                    method: 'DELETE'
                });
                
                if (!res.ok) throw new Error('Failed to delete result');
                
                const data = await res.json();
                enteredResults = data.entered_results;
                projections = data.projections;
                
                renderDashboard();
                // If currently editing this commune, reset form
                if (parseInt(selectedGeoIdInput.value) === geoId) {
                    resetForm();
                }
            } catch (err) {
                console.error('Error deleting result:', err);
                alert('Failed to remove result. Please try again.');
            }
        }
    });
}

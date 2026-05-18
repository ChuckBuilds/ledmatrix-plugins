/**
 * Custom Leagues Widget for Soccer Scoreboard Plugin
 *
 * Handles table-based soccer league editor for the soccer scoreboard plugin.
 * Allows adding, removing, and editing custom soccer league entries with
 * ESPN league code validation.
 *
 * This widget is plugin-specific and loaded from the plugin's widgets directory.
 *
 * @module CustomLeaguesWidget
 */

(function() {
    'use strict';

    // Ensure LEDMatrixWidgets registry exists
    if (typeof window.LEDMatrixWidgets === 'undefined') {
        console.error('[CustomLeaguesWidget] LEDMatrixWidgets registry not found. Load registry.js first.');
        return;
    }

    // Common ESPN league codes for suggestions
    const COMMON_LEAGUE_CODES = [
        { code: 'por.1', name: 'Liga Portugal' },
        { code: 'mex.1', name: 'Liga MX' },
        { code: 'arg.1', name: 'Argentina Primera División' },
        { code: 'bra.1', name: 'Brasileirão' },
        { code: 'ned.1', name: 'Eredivisie' },
        { code: 'sco.1', name: 'Scottish Premiership' },
        { code: 'tur.1', name: 'Turkish Süper Lig' },
        { code: 'bel.1', name: 'Belgian Pro League' },
        { code: 'aus.1', name: 'A-League' },
        { code: 'jpn.1', name: 'J1 League' },
        { code: 'kor.1', name: 'K League 1' },
        { code: 'chn.1', name: 'Chinese Super League' },
        { code: 'sau.1', name: 'Saudi Pro League' },
    ];

    /**
     * Register the custom-leagues widget
     */
    window.LEDMatrixWidgets.register('custom-leagues', {
        name: 'Custom Leagues Widget',
        version: '1.0.0',

        /**
         * Render the custom leagues widget
         */
        render: function(container, config, value, options) {
        },

        /**
         * Get current value from widget
         * @param {string} fieldId - Field ID
         * @returns {Array} Array of league objects
         */
        getValue: function(fieldId) {
            const tbody = document.getElementById(`${fieldId}_tbody`);
            if (!tbody) return [];

            const rows = tbody.querySelectorAll('.custom-league-row');
            const leagues = [];

            rows.forEach((row, index) => {
                const nameInput = row.querySelector('input[name*=".name"]');
                const codeInput = row.querySelector('input[name*=".league_code"]');
                const priorityInput = row.querySelector('input[name*=".priority"]');
                const enabledInput = row.querySelector('input[name*=".enabled"]');

                if (nameInput && codeInput) {
                    leagues.push({
                        name: nameInput.value,
                        league_code: codeInput.value,
                        priority: priorityInput ? parseInt(priorityInput.value, 10) || 50 : 50,
                        enabled: enabledInput ? enabledInput.checked : true
                    });
                }
            });

            return leagues;
        },

        /**
         * Set value in widget
         * @param {string} fieldId - Field ID
         * @param {Array} leagues - Array of league objects
         * @param {Object} options - Options containing fullKey and pluginId
         */
        setValue: function(fieldId, leagues, options) {
            if (!Array.isArray(leagues)) {
                console.error('[CustomLeaguesWidget] setValue expects an array');
                return;
            }

            if (!options || !options.fullKey || !options.pluginId) {
                throw new Error('CustomLeaguesWidget.setValue not implemented: requires options.fullKey and options.pluginId');
            }

            const tbody = document.getElementById(`${fieldId}_tbody`);
            if (!tbody) {
                console.warn(`[CustomLeaguesWidget] tbody not found for fieldId: ${fieldId}`);
                return;
            }

            // Clear existing rows
            tbody.innerHTML = '';

            // Build rows for each league
            leagues.forEach((league, index) => {
                const row = createLeagueRow(fieldId, options.fullKey, index, options.pluginId, league);
                tbody.appendChild(row);
            });
        },

        handlers: {}
    });

    /**
     * Create a league row element
     * @param {string} fieldId - Field ID
     * @param {string} fullKey - Full field key
     * @param {number} index - Row index
     * @param {string} pluginId - Plugin ID
     * @param {Object} league - League data (optional)
     * @returns {HTMLTableRowElement}
     */
    function createLeagueRow(fieldId, fullKey, index, pluginId, league = {}) {
        const row = document.createElement('tr');
        row.className = 'custom-league-row';
        row.setAttribute('data-index', index);

        // Name cell
        const nameCell = document.createElement('td');
        nameCell.className = 'px-4 py-3 whitespace-nowrap';
        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.name = `${fullKey}.${index}.name`;
        nameInput.value = league.name || '';
        nameInput.className = 'block w-full px-2 py-1 border border-gray-300 rounded text-sm';
        nameInput.placeholder = 'e.g., Liga Portugal';
        nameInput.required = true;
        nameCell.appendChild(nameInput);

        // League code cell
        const codeCell = document.createElement('td');
        codeCell.className = 'px-4 py-3 whitespace-nowrap';
        const codeContainer = document.createElement('div');
        codeContainer.className = 'flex items-center space-x-2';

        const codeInput = document.createElement('input');
        codeInput.type = 'text';
        codeInput.name = `${fullKey}.${index}.league_code`;
        codeInput.value = league.league_code || '';
        codeInput.className = 'block w-32 px-2 py-1 border border-gray-300 rounded text-sm';
        codeInput.placeholder = 'e.g., por.1';
        codeInput.required = true;
        codeInput.pattern = '^[a-z]{2,4}\\.[0-9]+$';
        codeInput.title = 'Format: xx.n (e.g., por.1)';

        // Suggestions button
        const suggestBtn = document.createElement('button');
        suggestBtn.type = 'button';
        suggestBtn.className = 'px-2 py-1 text-xs bg-gray-100 hover:bg-gray-200 rounded border';
        suggestBtn.title = 'Show common league codes';
        suggestBtn.innerHTML = '<i class="fas fa-list"></i>';
        suggestBtn.addEventListener('click', function(e) {
            e.preventDefault();
            showLeagueCodeSuggestions(codeInput, nameInput);
        });

        // Validation status indicator
        const validationIndicator = document.createElement('span');
        validationIndicator.className = 'validation-indicator text-sm';
        validationIndicator.id = `${fieldId}_validation_${index}`;

        // Add blur event for validation
        codeInput.addEventListener('blur', function() {
            validateLeagueCode(codeInput.value, validationIndicator, nameInput);
        });

        codeContainer.appendChild(codeInput);
        codeContainer.appendChild(suggestBtn);
        codeContainer.appendChild(validationIndicator);
        codeCell.appendChild(codeContainer);

        // Priority cell
        const priorityCell = document.createElement('td');
        priorityCell.className = 'px-4 py-3 whitespace-nowrap';
        const priorityInput = document.createElement('input');
        priorityInput.type = 'number';
        priorityInput.name = `${fullKey}.${index}.priority`;
        priorityInput.value = league.priority !== undefined ? league.priority : 50;
        priorityInput.min = 1;
        priorityInput.max = 100;
        priorityInput.className = 'block w-20 px-2 py-1 border border-gray-300 rounded text-sm text-center';
        priorityInput.title = 'Display priority (1=highest, 100=lowest). Predefined leagues use 1-8.';
        priorityCell.appendChild(priorityInput);

        // Enabled cell
        const enabledCell = document.createElement('td');
        enabledCell.className = 'px-4 py-3 whitespace-nowrap text-center';
        const enabledInput = document.createElement('input');
        enabledInput.type = 'checkbox';
        enabledInput.name = `${fullKey}.${index}.enabled`;
        enabledInput.checked = league.enabled !== false;
        enabledInput.value = 'true';
        enabledInput.className = 'h-4 w-4 text-blue-600';
        enabledCell.appendChild(enabledInput);

        // Remove cell
        const removeCell = document.createElement('td');
        removeCell.className = 'px-4 py-3 whitespace-nowrap text-center';
        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'text-red-600 hover:text-red-800 px-2 py-1';
        removeButton.addEventListener('click', function() {
            window.removeCustomLeagueRow(this);
        });
        const removeIcon = document.createElement('i');
        removeIcon.className = 'fas fa-trash';
        removeButton.appendChild(removeIcon);
        removeCell.appendChild(removeButton);

        // Append all cells
        row.appendChild(nameCell);
        row.appendChild(codeCell);
        row.appendChild(priorityCell);
        row.appendChild(enabledCell);
        row.appendChild(removeCell);

        return row;
    }

    /**
     * Validate a league code against ESPN API
     * @param {string} code - League code to validate
     * @param {HTMLElement} indicator - Status indicator element
     * @param {HTMLElement} nameInput - Name input to auto-fill
     */
    function validateLeagueCode(code, indicator, nameInput) {
        if (!code) {
            indicator.innerHTML = '';
            return;
        }

        if (!code.match(/^[a-z]{2,6}\.[0-9]+$/)) {
            indicator.innerHTML = '<span class="text-yellow-500" title="Invalid format. Use: xxx.n (e.g., por.1)">&#9888;</span>';
            return;
        }

        indicator.innerHTML = '<span class="text-gray-400">...</span>';

        // Validate directly against ESPN API
        // ESPN's public API generally allows CORS for read-only requests
        const espnUrl = `https://site.api.espn.com/apis/site/v2/sports/soccer/${encodeURIComponent(code)}/scoreboard`;

        fetch(espnUrl)
            .then(response => {
                if (response.ok) {
                    return response.json();
                }
                throw new Error(`HTTP ${response.status}`);
            })
            .then(data => {
                // Extract league name from response
                let leagueName = null;
                if (data.leagues && data.leagues.length > 0) {
                    const league = data.leagues[0];
                    leagueName = league.name || league.abbreviation || code;
                }

                indicator.innerHTML = '<span class="text-green-500" title="Valid league code">&#10003;</span>';

                // Auto-fill name if empty
                if (nameInput && !nameInput.value && leagueName) {
                    nameInput.value = leagueName;
                }
            })
            .catch(error => {
                console.warn('[CustomLeaguesWidget] Validation error:', error);
                if (error.message.includes('404')) {
                    indicator.innerHTML = '<span class="text-red-500" title="League code not found">&#10007;</span>';
                } else {
                    // Network error or CORS - show unknown status
                    indicator.innerHTML = '<span class="text-gray-400" title="Could not validate (network error)">?</span>';
                }
            });
    }

    /**
     * Show league code suggestions dropdown
     * @param {HTMLElement} codeInput - The league code input element
     * @param {HTMLElement} nameInput - The name input element
     */
    function showLeagueCodeSuggestions(codeInput, nameInput) {
        // Remove existing dropdown
        const existing = document.querySelector('.league-suggestions-dropdown');
        if (existing) {
            existing.remove();
            return; // Toggle behavior
        }

        const dropdown = document.createElement('div');
        dropdown.className = 'league-suggestions-dropdown absolute z-50 bg-white border border-gray-300 rounded shadow-lg mt-1 max-h-48 overflow-y-auto';
        dropdown.style.minWidth = '250px';

        COMMON_LEAGUE_CODES.forEach(league => {
            const item = document.createElement('div');
            item.className = 'px-3 py-2 hover:bg-gray-100 cursor-pointer text-sm';
            const codeEl = document.createElement('strong');
            codeEl.textContent = league.code;
            item.appendChild(codeEl);
            item.appendChild(document.createTextNode(' - ' + league.name));
            item.addEventListener('click', function() {
                codeInput.value = league.code;
                if (nameInput && !nameInput.value) {
                    nameInput.value = league.name;
                }
                dropdown.remove();
                // Trigger validation
                codeInput.dispatchEvent(new Event('blur'));
            });
            dropdown.appendChild(item);
        });

        // Position dropdown below the input
        const rect = codeInput.getBoundingClientRect();
        dropdown.style.position = 'fixed';
        dropdown.style.top = (rect.bottom + 2) + 'px';
        dropdown.style.left = rect.left + 'px';

        document.body.appendChild(dropdown);

        // Close on click outside
        setTimeout(() => {
            document.addEventListener('click', function closeDropdown(e) {
                if (!dropdown.contains(e.target) && e.target !== codeInput) {
                    dropdown.remove();
                    document.removeEventListener('click', closeDropdown);
                }
            });
        }, 100);
    }

    /**
     * Escape HTML to prevent XSS
     * @param {string} str - String to escape
     * @returns {string} Escaped string
     */
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    /**
     * Add a new custom league row to the table
     * @param {string} fieldId - Field ID
     * @param {string} fullKey - Full field key
     * @param {number} maxItems - Maximum number of items allowed
     * @param {string} pluginId - Plugin ID
     */
    window.addCustomLeagueRow = function(fieldId, fullKey, maxItems, pluginId) {
        const tbody = document.getElementById(fieldId + '_tbody');
        if (!tbody) return;

        const currentRows = tbody.querySelectorAll('.custom-league-row');
        if (currentRows.length >= maxItems) {
            const notifyFn = window.showNotification || alert;
            notifyFn(`Maximum ${maxItems} custom leagues allowed`, 'error');
            return;
        }

        const newIndex = currentRows.length;
        const row = createLeagueRow(fieldId, fullKey, newIndex, pluginId);
        tbody.appendChild(row);
    };

    /**
     * Remove a custom league row from the table
     * @param {HTMLElement} button - The remove button element
     */
    window.removeCustomLeagueRow = function(button) {
        const row = button.closest('tr');
        if (!row) return;

        if (confirm('Remove this custom league?')) {
            const tbody = row.parentElement;
            if (!tbody) return;

            row.remove();

            // Re-index remaining rows
            const rows = tbody.querySelectorAll('.custom-league-row');
            rows.forEach((r, index) => {
                r.setAttribute('data-index', index);
                r.querySelectorAll('input').forEach(input => {
                    const name = input.getAttribute('name');
                    if (name) {
                        input.setAttribute('name', name.replace(/\.\d+\./, `.${index}.`));
                    }
                    const id = input.id;
                    if (id) {
                        input.id = id.replace(/_validation_\d+$/, `_validation_${index}`);
                    }
                });
                // Update validation indicator spans and any attributes that reference them
                r.querySelectorAll('.validation-indicator').forEach(span => {
                    const oldId = span.id;
                    if (!oldId) return;
                    const newId = oldId.replace(/_validation_\d+$/, `_validation_${index}`);
                    span.id = newId;
                    // Update aria-describedby that references this span
                    r.querySelectorAll('[aria-describedby]').forEach(el => {
                        const ab = el.getAttribute('aria-describedby');
                        if (ab && ab.split(/\s+/).includes(oldId)) {
                            el.setAttribute('aria-describedby',
                                ab.split(/\s+/).map((id) => (id === oldId ? newId : id)).join(' '));
                        }
                    });
                    // Update label[for] that references this span
                    r.querySelectorAll('label[for]').forEach((label) => {
                        if (label.getAttribute('for') === oldId) {
                            label.setAttribute('for', newId);
                        }
                    });
                });
            });
        }
    };

})();

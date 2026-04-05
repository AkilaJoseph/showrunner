// ═══════════════════════════════════════════════
// ShowRunner — Client-side JavaScript
// ═══════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
    const toasts = document.querySelectorAll(".toast");
    toasts.forEach((t) => setTimeout(() => t.remove(), 3000));
});


// ── Seat Map Builder ──────────────────────────────────────────
//
// options:
//   rows         - number of rows
//   seatsPerRow  - default seat count (used when rowConfig not given)
//   rowConfig    - { "A": 8, "B": 2, "C": 6, ... } per-row overrides
//   bookedSeats  - ["A1","B3", ...]
//   selectable   - bool
//   price        - base ticket price
//   tiers        - [{ name, price, color, row_from, row_to }, ...]
// ─────────────────────────────────────────────────────────────
function buildSeatMap(containerId, options) {
    const {
        rows        = 5,
        seatsPerRow = 8,
        rowConfig   = {},        // per-row seat count overrides
        bookedSeats = [],
        selectable  = false,
        price       = 0,
        tiers       = [],
    } = options;

    const container = document.getElementById(containerId);
    if (!container) return;

    const LABELS      = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let selectedSeats = [];

    // How many seats in a given row letter
    function seatsInRow(rowLabel) {
        const l = rowLabel.toUpperCase();
        if (rowConfig && rowConfig[l] !== undefined) return rowConfig[l];
        return seatsPerRow;
    }

    // Tier for a given row letter
    function tierForRow(rowLabel) {
        const ri = LABELS.indexOf(rowLabel.toUpperCase());
        for (const t of tiers) {
            const fi = LABELS.indexOf((t.row_from || "").toUpperCase());
            const ti = LABELS.indexOf((t.row_to   || "").toUpperCase());
            if (ri >= fi && ri <= ti) return t;
        }
        return null;
    }

    function seatPrice(seatId) {
        const t = tierForRow(seatId[0]);
        return t ? t.price : price;
    }

    // ── render ────────────────────────────────────────────────
    function render() {
        container.innerHTML = "";

        // Stage indicator
        const stageWrap = document.createElement("div");
        stageWrap.className = "stage-indicator";
        stageWrap.innerHTML = '<div class="stage-line"></div>';
        container.appendChild(stageWrap);

        const stageLabel = document.createElement("div");
        stageLabel.className = "stage-label";
        stageLabel.textContent = "STAGE";
        container.appendChild(stageLabel);

        const grid = document.createElement("div");
        grid.className = "seat-grid";

        for (let r = 0; r < rows; r++) {
            const rowLabel  = LABELS[r];
            const seatCount = seatsInRow(rowLabel);
            const tier      = tierForRow(rowLabel);

            const rowDiv = document.createElement("div");
            rowDiv.className = "seat-row";

            // Row label
            const label = document.createElement("span");
            label.className   = "seat-row-label";
            label.textContent = rowLabel;
            if (tier) label.style.color = tier.color;
            rowDiv.appendChild(label);

            // Seats
            for (let c = 0; c < seatCount; c++) {
                const seatId   = `${rowLabel}${c + 1}`;
                const btn      = document.createElement("button");
                btn.type       = "button";
                btn.className  = "seat";
                btn.textContent = c + 1;
                btn.title      = seatId + (tier ? ` — ${tier.name}` : "");

                const isBooked   = bookedSeats.includes(seatId);
                const isSelected = selectedSeats.includes(seatId);

                if (isBooked) {
                    btn.classList.add("seat-booked");
                    btn.disabled = true;
                } else if (isSelected) {
                    btn.classList.add("seat-selected");
                    if (tier) {
                        btn.style.background = tier.color;
                        btn.style.color      = "#111120";
                    }
                } else {
                    btn.classList.add("seat-available");
                    if (tier) {
                        btn.style.background = tier.color + "22";
                        btn.style.border     = `1px solid ${tier.color}55`;
                    }
                }

                if (selectable && !isBooked) {
                    btn.addEventListener("click", () => {
                        const idx = selectedSeats.indexOf(seatId);
                        if (idx === -1) selectedSeats.push(seatId);
                        else           selectedSeats.splice(idx, 1);
                        render();
                        updateSelection();
                    });
                } else if (!selectable) {
                    btn.style.cursor = "default";
                }
                rowDiv.appendChild(btn);
            }
            grid.appendChild(rowDiv);
        }
        container.appendChild(grid);

        // Legend
        if (tiers.length > 0) {
            const legend = document.createElement("div");
            legend.className = "tier-legend";
            tiers.forEach(t => {
                const item = document.createElement("div");
                item.className = "tier-legend-item";
                item.innerHTML = `
                    <span class="tier-legend-dot" style="background:${t.color}"></span>
                    <span class="tier-legend-name">${t.name}</span>
                    <span class="tier-legend-price">${Number(t.price).toLocaleString()} TZS</span>
                `;
                legend.appendChild(item);
            });
            container.appendChild(legend);
        } else if (selectable) {
            const legend = document.createElement("div");
            legend.className = "seat-legend";
            legend.innerHTML = `
                <span class="seat-legend-item">
                    <span class="seat-legend-dot" style="background:#26264a;"></span> Available
                </span>
                <span class="seat-legend-item">
                    <span class="seat-legend-dot" style="background:var(--accent-gold);"></span> Selected
                </span>
                <span class="seat-legend-item">
                    <span class="seat-legend-dot" style="background:#2a2a40;"></span> Booked
                </span>
            `;
            container.appendChild(legend);
        }
    }

    // ── selection update ──────────────────────────────────────
    function updateSelection() {
        const hiddenInput = document.getElementById("selected_seats");
        if (hiddenInput) hiddenInput.value = selectedSeats.join(",");

        const infoDiv = document.getElementById("selection-info");
        if (infoDiv) {
            if (selectedSeats.length === 0) {
                infoDiv.style.display = "none";
            } else {
                infoDiv.style.display = "block";

                const breakdown = {};
                let   total     = 0;
                selectedSeats.forEach(sId => {
                    const t   = tierForRow(sId[0]);
                    const p   = t ? t.price : price;
                    const key = t ? t.name  : "Standard";
                    const col = t ? t.color : "var(--accent-gold)";
                    if (!breakdown[key]) breakdown[key] = { price: p, count: 0, color: col };
                    breakdown[key].count++;
                    total += p;
                });

                let html = `<p class="selection-seats">Selected: <strong>${selectedSeats.join(", ")}</strong></p>`;
                if (Object.keys(breakdown).length > 1 || tiers.length > 0) {
                    html += `<div class="selection-breakdown">`;
                    for (const [name, info] of Object.entries(breakdown)) {
                        html += `<span class="selection-tier-line">
                            <span class="selection-tier-dot" style="background:${info.color}"></span>
                            ${info.count} × ${name}
                            <span style="color:var(--text-muted);margin-left:4px">${(info.count * info.price).toLocaleString()} TZS</span>
                        </span>`;
                    }
                    html += `</div>`;
                }
                html += `<p class="selection-total">Total: ${total.toLocaleString()} TZS</p>`;
                infoDiv.innerHTML = html;
            }
        }

        const submitBtn = document.getElementById("book-submit-btn");
        if (submitBtn) {
            let total = 0;
            selectedSeats.forEach(sId => { total += seatPrice(sId); });
            if (selectedSeats.length > 0) {
                submitBtn.disabled    = false;
                submitBtn.textContent = `Confirm Booking — ${total.toLocaleString()} TZS`;
            } else {
                submitBtn.disabled    = true;
                submitBtn.textContent = "Select seats to book";
            }
        }
    }

    render();
    updateSelection();
}


// ── Verify Input Auto-Format ──────────────────────────────────
// Handles new 6-char codes (XXXXXX) and legacy 12-char codes (XXXX-XXXX-XXXX)
function formatVerifyInput(input) {
    const val = input.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    if (val.length <= 6) {
        // New format — no dashes, plain 6 chars
        input.value = val;
    } else {
        // Legacy format — add dashes every 4 chars
        let formatted = "";
        for (let i = 0; i < val.length && i < 12; i++) {
            if (i > 0 && i % 4 === 0) formatted += "-";
            formatted += val[i];
        }
        input.value = formatted;
    }
}


// ── PWA: Push Notification Permission Button ──────────────────
// Attach to any element with data-push-btn to trigger permission request
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-push-btn]").forEach(btn => {
        // Hide button if already subscribed or not supported
        if (!('Notification' in window) || !('serviceWorker' in navigator)) {
            btn.style.display = "none";
            return;
        }
        if (Notification.permission === "granted") {
            btn.textContent = "🔔 Notifications On";
            btn.disabled = true;
        }
        btn.addEventListener("click", async () => {
            btn.disabled = true;
            btn.textContent = "Enabling…";
            const ok = await (window.SR && window.SR.requestPush ? window.SR.requestPush() : Promise.resolve(false));
            btn.textContent = ok ? "🔔 Notifications On" : "Notifications unavailable";
        });
    });
});

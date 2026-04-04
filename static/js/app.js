// ═══════════════════════════════════════════════
// ShowRunner — Client-side JavaScript
// ═══════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
    // Auto-dismiss toasts
    const toasts = document.querySelectorAll(".toast");
    toasts.forEach((t) => {
        setTimeout(() => t.remove(), 3000);
    });
});


// ── Seat Map Builder ──
function buildSeatMap(containerId, options) {
    const {
        rows = 5,
        seatsPerRow = 8,
        bookedSeats = [],
        selectable = false,
        onSelectionChange = null,
        price = 0,
    } = options;

    const container = document.getElementById(containerId);
    if (!container) return;

    const labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let selectedSeats = [];

    function render() {
        container.innerHTML = "";

        // Stage
        const stageDiv = document.createElement("div");
        stageDiv.className = "stage-indicator";
        stageDiv.innerHTML = '<div class="stage-line"></div>';
        container.appendChild(stageDiv);

        const stageLabel = document.createElement("div");
        stageLabel.className = "stage-label";
        stageLabel.textContent = "STAGE";
        container.appendChild(stageLabel);

        // Grid
        const grid = document.createElement("div");
        grid.className = "seat-grid";

        for (let r = 0; r < rows; r++) {
            const rowDiv = document.createElement("div");
            rowDiv.className = "seat-row";

            const rowLabel = document.createElement("span");
            rowLabel.className = "seat-row-label";
            rowLabel.textContent = labels[r];
            rowDiv.appendChild(rowLabel);

            for (let c = 0; c < seatsPerRow; c++) {
                const seatId = `${labels[r]}${c + 1}`;
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "seat";
                btn.textContent = c + 1;
                btn.title = seatId;

                const isBooked = bookedSeats.includes(seatId);
                const isSelected = selectedSeats.includes(seatId);

                if (isBooked) {
                    btn.classList.add("seat-booked");
                    btn.disabled = true;
                } else if (isSelected) {
                    btn.classList.add("seat-selected");
                } else {
                    btn.classList.add("seat-available");
                }

                if (selectable && !isBooked) {
                    btn.addEventListener("click", () => {
                        if (selectedSeats.includes(seatId)) {
                            selectedSeats = selectedSeats.filter((s) => s !== seatId);
                        } else {
                            selectedSeats.push(seatId);
                        }
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
        if (selectable) {
            const legend = document.createElement("div");
            legend.className = "seat-legend";
            legend.innerHTML = `
                <span class="seat-legend-item">
                    <span class="seat-legend-dot" style="background: #2d2d44;"></span> Available
                </span>
                <span class="seat-legend-item">
                    <span class="seat-legend-dot" style="background: #f0c040;"></span> Selected
                </span>
                <span class="seat-legend-item">
                    <span class="seat-legend-dot" style="background: #3a3a4e;"></span> Booked
                </span>
            `;
            container.appendChild(legend);
        }
    }

    function updateSelection() {
        // Update hidden input
        const hiddenInput = document.getElementById("selected_seats");
        if (hiddenInput) {
            hiddenInput.value = selectedSeats.join(",");
        }

        // Update info display
        const infoDiv = document.getElementById("selection-info");
        if (infoDiv) {
            if (selectedSeats.length > 0) {
                infoDiv.style.display = "block";
                infoDiv.innerHTML = `
                    <p class="selection-seats">Selected: <strong>${selectedSeats.join(", ")}</strong></p>
                    <p class="selection-total">Total: ${(selectedSeats.length * price).toLocaleString()} TZS</p>
                `;
            } else {
                infoDiv.style.display = "none";
            }
        }

        // Update submit button
        const submitBtn = document.getElementById("book-submit-btn");
        if (submitBtn) {
            const total = selectedSeats.length * price;
            if (selectedSeats.length > 0) {
                submitBtn.disabled = false;
                submitBtn.textContent = `Confirm Booking — ${total.toLocaleString()} TZS`;
            } else {
                submitBtn.disabled = true;
                submitBtn.textContent = "Select seats to book";
            }
        }

        if (onSelectionChange) {
            onSelectionChange(selectedSeats);
        }
    }

    render();
    updateSelection();
}


// ── Verify Input Auto-Format ──
function formatVerifyInput(input) {
    let val = input.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    let formatted = "";
    for (let i = 0; i < val.length && i < 12; i++) {
        if (i > 0 && i % 4 === 0) formatted += "-";
        formatted += val[i];
    }
    input.value = formatted;
}

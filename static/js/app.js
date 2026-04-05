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
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-push-btn]").forEach(btn => {
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


// ── Global Lightbox ───────────────────────────────────────────
// Usage:
//   LB.open(items, startIndex)
//   items: [{ type:'image'|'video'|'embed', src, caption, download }]
(function() {
    const overlay  = document.getElementById('lb-overlay');
    if (!overlay) return;

    const media    = document.getElementById('lb-media');
    const footer   = document.getElementById('lb-footer');
    const caption  = document.getElementById('lb-caption');
    const counter  = document.getElementById('lb-counter');
    const closeBtn = document.getElementById('lb-close');
    const prevBtn  = document.getElementById('lb-prev');
    const nextBtn  = document.getElementById('lb-next');

    let items   = [];
    let current = 0;
    let activeVid = null;

    function stopActiveVid() {
        if (activeVid) { activeVid.pause(); activeVid = null; }
    }

    function show(idx) {
        stopActiveVid();
        current = ((idx % items.length) + items.length) % items.length;
        const item = items[current];

        // Counter
        counter.textContent = items.length > 1 ? `${current + 1} / ${items.length}` : '';

        // Nav visibility
        prevBtn.classList.toggle('lb-hidden', items.length <= 1);
        nextBtn.classList.toggle('lb-hidden', items.length <= 1);

        // Render media
        media.innerHTML = '';
        if (item.type === 'image') {
            const img = document.createElement('img');
            img.src = item.src;
            img.alt = item.caption || '';
            media.appendChild(img);
        } else if (item.type === 'video') {
            const vid = document.createElement('video');
            vid.src = item.src;
            vid.controls = true;
            vid.autoplay = true;
            vid.playsInline = true;
            media.appendChild(vid);
            activeVid = vid;
        } else if (item.type === 'embed') {
            const fr = document.createElement('iframe');
            fr.src = item.src;
            fr.allowFullscreen = true;
            fr.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture';
            media.appendChild(fr);
        }

        // Caption & action buttons
        caption.textContent = item.caption || '';
        // Remove old action buttons, keep caption
        footer.querySelectorAll('.lb-action-btn').forEach(b => b.remove());

        if (item.download && item.type === 'image') {
            const a = document.createElement('a');
            a.className = 'lb-action-btn lb-download';
            a.href = item.download;
            a.download = '';
            a.target = '_blank';
            a.rel = 'noopener';
            a.innerHTML = '<i class="bi bi-download"></i> Save Photo';
            footer.appendChild(a);
        }
        if (item.type === 'video' && item.src) {
            const a = document.createElement('a');
            a.className = 'lb-action-btn lb-download';
            a.href = item.src;
            a.download = '';
            a.target = '_blank';
            a.rel = 'noopener';
            a.innerHTML = '<i class="bi bi-download"></i> Save Video';
            footer.appendChild(a);
        }
    }

    function open(newItems, startIndex) {
        items   = newItems;
        overlay.classList.add('open');
        document.body.style.overflow = 'hidden';
        show(startIndex || 0);
    }

    function close() {
        stopActiveVid();
        overlay.classList.remove('open');
        document.body.style.overflow = '';
        media.innerHTML = '';
        items = [];
    }

    closeBtn.addEventListener('click', close);
    prevBtn.addEventListener('click', () => show(current - 1));
    nextBtn.addEventListener('click', () => show(current + 1));

    // Click backdrop to close
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });

    // Keyboard nav
    document.addEventListener('keydown', e => {
        if (!overlay.classList.contains('open')) return;
        if (e.key === 'Escape')      close();
        if (e.key === 'ArrowLeft')   show(current - 1);
        if (e.key === 'ArrowRight')  show(current + 1);
    });

    // Touch swipe
    let touchX = null;
    overlay.addEventListener('touchstart', e => { touchX = e.touches[0].clientX; }, { passive: true });
    overlay.addEventListener('touchend', e => {
        if (touchX === null) return;
        const dx = e.changedTouches[0].clientX - touchX;
        if (Math.abs(dx) > 50) show(dx < 0 ? current + 1 : current - 1);
        touchX = null;
    });

    // Expose globally
    window.LB = { open };

    // ── Auto-wire public photo grids ──────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        // Public photo grids — .photo-item-public
        document.querySelectorAll('.photo-grid-public').forEach(grid => {
            const imgs = [...grid.querySelectorAll('.photo-item-public img')];
            const lbItems = imgs.map(img => ({
                type:     'image',
                src:      img.src,
                caption:  img.alt || '',
                download: img.src,
            }));
            imgs.forEach((img, i) => {
                img.closest('.photo-item-public').addEventListener('click', () => {
                    LB.open(lbItems, i);
                });
            });
        });

        // Organizer photo grids — .photo-item (no delete btn interference)
        document.querySelectorAll('.photo-grid').forEach(grid => {
            const items = [...grid.querySelectorAll('.photo-item')];
            const lbItems = items.map(item => {
                const img = item.querySelector('img');
                const cap = item.querySelector('.photo-caption');
                return img ? { type:'image', src:img.src, caption: cap ? cap.textContent : '', download: img.src } : null;
            }).filter(Boolean);
            items.forEach((item, i) => {
                if (!lbItems[i]) return;
                const img = item.querySelector('img');
                if (!img) return;
                img.style.cursor = 'zoom-in';
                img.addEventListener('click', (e) => {
                    e.stopPropagation(); // don't trigger delete form
                    LB.open(lbItems, i);
                });
            });
        });

        // Video reel items — handled by TikTok reel in book_event.html (opens tk-reel)
        // Lightbox handles photos only.
    });
})();

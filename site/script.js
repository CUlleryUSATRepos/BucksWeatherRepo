const DATA_URL = '../data/dashboard/latest.json?t=${Date.now()}';

async function loadDashboard() {
    try {
        const response = await fetch(DATA_URL);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        renderGeneratedAt(data.generated_at);
        renderCurrent(data.current);
        renderAlerts(data.alerts || []);
        renderSummary(data.summary || "");
        renderChart(data.chart || []);
    } catch (error) {
        renderError(error);
        console.error("Dashboard load failed:", error);
    }
}

function renderGeneratedAt(timestamp) {
    const el = document.getElementById("generated-at");

    if (!timestamp) {
        el.textContent = "Latest update time unavailable";
        return;
    }

    const dt = new Date(timestamp);

    el.textContent = `Updated ${dt.toLocaleString("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit"
    })}`;
}

function renderCurrent(current) {
    document.getElementById("current-temp").textContent =
        current?.avg_temp != null ? `${current.avg_temp}°F` : "--";

    document.getElementById("current-humidity").textContent =
        current?.avg_humidity != null ? `${current.avg_humidity}%` : "--";

    document.getElementById("current-wind").textContent =
        current?.avg_wind != null ? `${current.avg_wind} mph` : "--";

    document.getElementById("current-conditions").textContent =
        current?.conditions || "--";
}

function renderAlerts(alerts) {
    const countEl = document.getElementById("alerts-count");
    const listEl = document.getElementById("alerts-list");

    countEl.textContent = alerts.length;

    if (!alerts.length) {
        listEl.innerHTML = `<p class="muted">No active alerts in this pull.</p>`;
        return;
    }

    listEl.innerHTML = alerts.map(alert => {
        const effective = formatShortDateTime(alert.effective);
        const expires = formatShortDateTime(alert.expires);

        return `
            <article class="alert-item">
                <h3>${escapeHtml(alert.event || "Weather Alert")}</h3>
                <div>${escapeHtml(alert.headline || "")}</div>
                <p class="alert-meta">
                    Severity: ${escapeHtml(alert.severity || "Unknown")}<br>
                    Effective: ${escapeHtml(effective)}<br>
                    Expires: ${escapeHtml(expires)}
                </p>
            </article>
        `;
    }).join("");
}

function renderSummary(summary) {
    const el = document.getElementById("summary-text");

    if (!summary) {
        el.innerHTML = "<p>No summary available.</p>";
        return;
    }

    const paragraphs = summary
        .split("\n")
        .map(line => line.trim())
        .filter(Boolean);

    el.innerHTML = paragraphs.map(p => `<p>${escapeHtml(p)}</p>`).join("");
}

function renderChart(chartData) {
    const canvas = document.getElementById("weather-chart");
    const ctx = canvas.getContext("2d");

    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    if (!chartData.length) {
        ctx.font = "16px Arial";
        ctx.fillStyle = "#6b7280";
        ctx.fillText("No chart data available.", 40, 60);
        return;
    }

    const padding = { top: 35, right: 80, bottom: 105, left: 80 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const baselineY = padding.top + plotHeight;

    const temps = chartData
        .map(d => d.temp)
        .filter(v => v != null);

    const precips = chartData
        .map(d => d.precip)
        .filter(v => v != null);

    const minTemp = Math.floor(Math.min(...temps) - 2);
    const maxTemp = Math.ceil(Math.max(...temps) + 2);
    const rawMaxPrecip = precips.length ? Math.max(...precips) : 0;
    const maxPrecip = Math.max(20, Math.ceil(rawMaxPrecip / 5) * 5);

    function xScale(index) {
        if (chartData.length === 1) {
            return padding.left + plotWidth / 2;
        }
        return padding.left + (index / (chartData.length - 1)) * plotWidth;
    }

    function yTempScale(value) {
        return padding.top + ((maxTemp - value) / (maxTemp - minTemp)) * plotHeight;
    }

    function yPrecipScale(value) {
        return padding.top + ((maxPrecip - value) / maxPrecip) * plotHeight;
    }

    drawGrid(ctx, padding, plotWidth, plotHeight);
    drawPrecipBars(ctx, chartData, xScale, yPrecipScale, baselineY);
    drawTempLine(ctx, chartData, xScale, yTempScale);
    drawXAxisLabels(ctx, chartData, xScale, baselineY);
    drawYAxisLabels(ctx, padding.left, padding.top, plotHeight, minTemp, maxTemp);
    drawRightYAxisLabels(ctx, width - padding.right, padding.top, plotHeight, maxPrecip);
    drawAxisLine(ctx, padding.left, width - padding.right, baselineY);
}

function drawGrid(ctx, padding, plotWidth, plotHeight) {
    const steps = 5;
    ctx.strokeStyle = "#eef2f7";
    ctx.lineWidth = 1;

    for (let i = 0; i <= steps; i++) {
        const y = padding.top + (i / steps) * plotHeight;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(padding.left + plotWidth, y);
        ctx.stroke();
    }
}

function drawPrecipBars(ctx, chartData, xScale, yPrecipScale, baselineY) {
    const barWidth = Math.max(5, Math.min(12, 620 / chartData.length));

    ctx.fillStyle = "#22c55e";

    chartData.forEach((point, index) => {
        const precip = point.precip ?? 0;
        const x = xScale(index) - barWidth / 2;
        const y = yPrecipScale(precip);
        const height = baselineY - y;

        if (height > 0) {
            ctx.fillRect(x, y, barWidth, height);
        }
    });
}

function drawTempLine(ctx, chartData, xScale, yTempScale) {
    ctx.strokeStyle = "#1d4ed8";
    ctx.lineWidth = 3;
    ctx.beginPath();

    let started = false;

    chartData.forEach((point, index) => {
        if (point.temp == null) return;

        const x = xScale(index);
        const y = yTempScale(point.temp);

        if (!started) {
            ctx.moveTo(x, y);
            started = true;
        } else {
            ctx.lineTo(x, y);
        }
    });

    ctx.stroke();

    ctx.fillStyle = "#1d4ed8";
    chartData.forEach((point, index) => {
        if (point.temp == null) return;

        const x = xScale(index);
        const y = yTempScale(point.temp);

        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fill();
    });
}

function drawXAxisLabels(ctx, chartData, xScale, baselineY) {
    ctx.fillStyle = "#6b7280";
    ctx.font = "12px Arial";
    ctx.textAlign = "center";

    const labelEvery = Math.max(1, Math.ceil(chartData.length / 5));

    chartData.forEach((point, index) => {
        if (index % labelEvery !== 0 && index !== chartData.length - 1) return;

        const dt = new Date(point.time);
        const weekday = dt.toLocaleString("en-US", { weekday: "short" });
        const hour = dt.toLocaleString("en-US", { hour: "numeric" });
        const label = `${weekday} ${hour}`;

        const x = xScale(index);

        ctx.save();
        ctx.translate(x, baselineY + 34);
        ctx.rotate(-Math.PI / 7);
        ctx.fillText(label, 0, 0);
        ctx.restore();
    });
}

function drawYAxisLabels(ctx, leftX, topY, plotHeight, minTemp, maxTemp) {
    const steps = 5;
    ctx.fillStyle = "#6b7280";
    ctx.font = "12px Arial";
    ctx.textAlign = "right";

    for (let i = 0; i <= steps; i++) {
        const value = maxTemp - ((maxTemp - minTemp) * i / steps);
        const y = topY + (i / steps) * plotHeight + 4;
        ctx.fillText(`${Math.round(value)}°`, leftX - 16, y);
    }
}

function drawRightYAxisLabels(ctx, rightX, topY, plotHeight, maxPrecip) {
    const steps = 5;
    ctx.fillStyle = "#6b7280";
    ctx.font = "12px Arial";
    ctx.textAlign = "left";

    for (let i = 0; i <= steps; i++) {
        const value = maxPrecip - (maxPrecip * i / steps);
        const y = topY + (i / steps) * plotHeight + 4;
        ctx.fillText(`${Math.round(value)}%`, rightX + 16, y);
    }
}

function drawAxisLine(ctx, startX, endX, y) {
    ctx.strokeStyle = "#9ca3af";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(startX, y);
    ctx.lineTo(endX, y);
    ctx.stroke();
}

function formatShortDateTime(value) {
    if (!value) return "Unknown";

    const dt = new Date(value);

    if (Number.isNaN(dt.getTime())) {
        return value;
    }

    return dt.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit"
    });
}

function escapeHtml(str) {
    return String(str)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function renderError(error) {
    const main = document.querySelector(".dashboard");
    main.innerHTML = `
        <div class="error-box">
            <strong>Dashboard failed to load.</strong><br>
            ${escapeHtml(error.message || "Unknown error")}
        </div>
    `;
}

loadDashboard();
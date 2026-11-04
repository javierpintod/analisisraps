/**
 * SENA - Sistema de Análisis de Avance por RAPs
 * Controlador Frontend Interactivo con Autenticación JWT (RFC 7519 HS256) y SQLite/Liquibase
 */

document.addEventListener("DOMContentLoaded", () => {
    const JWT_STORAGE_KEY = "sena_jwt_token";

    // Estado global de la aplicación
    let currentAnalysis = null;
    let selectedStates = new Set();
    let currentRapFilter = "all";
    let currentAprFilter = "all";
    let currentUser = null;
    let currentClaims = null;
    let currentPermisos = [];
    let regPage = 1;
    let regPages = 1;

    function can(permiso) {
        return currentPermisos.includes(permiso);
    }

    // Elementos del DOM
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const fileInfo = document.getElementById("file-info");
    const fileNameText = document.getElementById("file-name-text");
    const btnClearFile = document.getElementById("btn-clear-file");
    const btnLoadSample = document.getElementById("btn-load-sample");
    const btnExportExcel = document.getElementById("btn-export-excel");
    const emptyState = document.getElementById("empty-state");
    const dashboardContent = document.getElementById("dashboard-content");
    const controlsBar = document.getElementById("controls-bar");
    const stateChipsContainer = document.getElementById("state-chips");
    const btnApplyFilters = document.getElementById("btn-apply-filters");
    const inputUmbralVerde = document.getElementById("input-umbral-verde");
    const inputUmbralAmarillo = document.getElementById("input-umbral-amarillo");
    const btnSaveSnapshot = document.getElementById("btn-save-snapshot");
    const inputHistObs = document.getElementById("input-hist-obs");

    // Elementos de Login y Sesión JWT
    const loginBackdrop = document.getElementById("login-backdrop");
    const loginForm = document.getElementById("login-form");
    const loginUsername = document.getElementById("login-username");
    const loginPassword = document.getElementById("login-password");
    const loginError = document.getElementById("login-error");
    const userSessionBar = document.getElementById("user-session-bar");
    const userSessionName = document.getElementById("user-session-name");
    const userSessionRole = document.getElementById("user-session-role");
    const btnShowJwt = document.getElementById("btn-show-jwt");
    const btnLogout = document.getElementById("btn-logout");

    // Modal
    const modalBackdrop = document.getElementById("modal-backdrop");
    const btnCloseModal = document.getElementById("btn-close-modal");
    const modalAprName = document.getElementById("modal-apr-name");
    const modalAprDoc = document.getElementById("modal-apr-doc");
    const modalAprContent = document.getElementById("modal-apr-content");

    // Toast
    const toast = document.getElementById("toast");

    function showToast(message, isError = false) {
        toast.textContent = message;
        toast.style.background = isError ? "#EF4444" : "#1F2937";
        toast.style.borderColor = isError ? "#DC2626" : "rgba(57, 169, 0, 0.4)";
        toast.style.display = "block";
        setTimeout(() => {
            toast.style.display = "none";
        }, 3500);
    }

    // -------------------------------------------------------------
    // GESTIÓN DE TOKEN JWT Y CLIENTE HTTP AUTENTICADO
    // -------------------------------------------------------------
    function getToken() {
        return localStorage.getItem(JWT_STORAGE_KEY);
    }

    function setToken(token) {
        if (token) {
            localStorage.setItem(JWT_STORAGE_KEY, token);
        } else {
            localStorage.removeItem(JWT_STORAGE_KEY);
        }
    }

    function showLoginScreen(errorMsg = "") {
        userSessionBar.style.display = "none";
        loginBackdrop.style.display = "flex";
        if (errorMsg) {
            loginError.textContent = errorMsg;
            loginError.style.display = "block";
        } else {
            loginError.style.display = "none";
        }
    }

    function updateSessionHeader(user, claims, permisos) {
        currentUser = user;
        currentClaims = claims;
        currentPermisos = permisos || [];
        document.querySelectorAll(".perm-registros-ver").forEach(el => el.style.display = can("registros.ver") ? "" : "none");
        document.querySelectorAll(".perm-auditoria-ver").forEach(el => el.style.display = can("auditoria.ver") ? "" : "none");
        if (dropZone) dropZone.style.display = can("analisis.cargar") ? "" : "none";
        if (user) {
            userSessionName.textContent = user.nombre || user.username;
            userSessionRole.textContent = user.rol || "INSTRUCTOR";
            userSessionBar.style.display = "inline-flex";
            loginBackdrop.style.display = "none";
        } else {
            userSessionBar.style.display = "none";
        }
    }

    async function apiFetch(url, options = {}) {
        const token = getToken();
        const headers = Object.assign({}, options.headers || {});
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }
        const response = await fetch(url, Object.assign({}, options, { headers }));
        if (response.status === 401) {
            setToken(null);
            showLoginScreen("Tu sesión ha expirado o requiere autenticación JWT.");
            throw new Error("Sesión no autenticada (401 Unauthorized)");
        }
        if (response.status === 403) {
            let msg = "Acceso denegado (403)";
            try { msg = (await response.json()).error || msg; } catch (e) { /* sin cuerpo JSON */ }
            throw new Error(msg);
        }
        return response;
    }

    // Eventos del formulario de Login
    document.querySelectorAll(".btn-demo-cred").forEach(btn => {
        btn.addEventListener("click", () => {
            loginUsername.value = btn.dataset.user;
            loginPassword.value = btn.dataset.pass;
            loginError.style.display = "none";
        });
    });

    loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        loginError.style.display = "none";

        const username = loginUsername.value.trim();
        const password = loginPassword.value;

        try {
            const res = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || "Credenciales inválidas");
            }

            setToken(data.token);
            updateSessionHeader(data.user, data.claims, data.permisos);
            loginPassword.value = "";
            showToast(`Bienvenido, ${data.user.nombre} (Token JWT activo)`);
            await loadSampleData(false);
        } catch (err) {
            loginError.textContent = err.message;
            loginError.style.display = "block";
        }
    });

    btnLogout.addEventListener("click", async () => {
        try {
            await apiFetch("/api/auth/logout", { method: "POST" });
        } catch (e) {
            // Ignorar si ya expiró
        }
        setToken(null);
        currentUser = null;
        currentClaims = null;
        resetAppState();
        showLoginScreen();
        showToast("Sesión cerrada y token JWT revocado");
    });

    btnShowJwt.addEventListener("click", () => {
        const token = getToken();
        if (!token) return;
        modalAprName.textContent = "🔑 Token de Autenticación JWT Activo (RFC 7519)";
        modalAprDoc.textContent = `Usuario: ${currentUser ? currentUser.username : '-'}  |  Algoritmo: HS256  |  Estado: FIRMADO Y VÁLIDO`;

        const payloadPretty = JSON.stringify(currentClaims || {}, null, 2);
        modalAprContent.innerHTML = `
            <div class="modal-section-title" style="color: var(--color-green); margin-top: 0;">Token Bearer Codificado (Header.Payload.Signature)</div>
            <div class="jwt-code-block">${escapeHtml(token)}</div>
            <div class="modal-section-title" style="color: #38BDF8;">Claims Decodificados del Payload (Verificados con HMAC-SHA256)</div>
            <pre class="jwt-code-block" style="color: #A7F3D0; white-space: pre-wrap;">${escapeHtml(payloadPretty)}</pre>
        `;
        modalBackdrop.style.display = "flex";
    });

    async function checkInitialAuth() {
        const token = getToken();
        if (!token) {
            showLoginScreen();
            return;
        }
        try {
            const res = await apiFetch("/api/auth/me");
            const data = await res.json();
            if (data.success && data.authenticated) {
                updateSessionHeader(data.user, data.claims, data.permisos);
                await loadSampleData(false);
            } else {
                showLoginScreen();
            }
        } catch (err) {
            showLoginScreen();
        }
    }

    // -------------------------------------------------------------
    // EVENTOS DE SUBIDA DE ARCHIVO (DRAG & DROP)
    // -------------------------------------------------------------
    dropZone.addEventListener("click", () => fileInput.click());

    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.add("dragover");
        });
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.remove("dragover");
        });
    });

    dropZone.addEventListener("drop", (e) => {
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            handleFileUpload(files[0]);
        }
    });

    fileInput.addEventListener("change", (e) => {
        const files = e.target.files;
        if (files && files.length > 0) {
            handleFileUpload(files[0]);
        }
    });

    btnClearFile.addEventListener("click", (e) => {
        e.stopPropagation();
        resetAppState();
    });

    function resetAppState() {
        fileInput.value = "";
        currentAnalysis = null;
        fileInfo.style.display = "none";
        emptyState.style.display = "flex";
        dashboardContent.style.display = "none";
        controlsBar.style.display = "none";
        btnExportExcel.disabled = true;
    }

    async function handleFileUpload(file) {
        fileNameText.textContent = file.name;
        fileInfo.style.display = "inline-flex";

        showToast("Procesando archivo SENA y registrando en BD...");

        try {
            const base64 = await readFileAsBase64(file);
            const res = await apiFetch("/api/upload", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    filename: file.name,
                    content_base64: base64
                })
            });

            const data = await res.json();
            if (!data.success) {
                throw new Error(data.error || "Error al procesar el archivo");
            }

            setupStateChips(data.states);
            renderDashboard(data.analysis);
            await loadHistoryData();
            loadCargas();
            const recMsg = data.records_info ? ` ${data.records_info.mensaje}` : "";
            showToast(`¡Análisis completado y guardado en el histórico!${recMsg}`);
        } catch (err) {
            console.error(err);
            showToast(err.message, true);
        }
    }

    function readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const result = reader.result;
                const base64 = result.split(",")[1];
                resolve(base64);
            };
            reader.onerror = error => reject(error);
            reader.readAsDataURL(file);
        });
    }

    // -------------------------------------------------------------
    // CARGAR ARCHIVO DE MUESTRA (DEMO)
    // -------------------------------------------------------------
    async function loadSampleData(showNotification = true) {
        if (showNotification) showToast("Cargando archivo de prueba SENA...");
        try {
            const res = await apiFetch("/api/sample");
            const data = await res.json();
            if (!data.success) {
                throw new Error(data.error || "No se pudo cargar el archivo demo");
            }

            fileNameText.textContent = `${data.filename} (Ficha ${data.analysis.meta.ficha})`;
            fileInfo.style.display = "inline-flex";

            setupStateChips(data.states);
            renderDashboard(data.analysis);
            await loadHistoryData();
            loadCargas();
            if (showNotification) showToast("Reporte cargado con éxito");

        } catch (err) {
            console.error(err);
            if (showNotification) showToast(err.message, true);
        }
    }

    btnLoadSample.addEventListener("click", () => loadSampleData(true));


    // -------------------------------------------------------------
    // FILTROS DE ESTADO Y UMBRALES
    // -------------------------------------------------------------
    function setupStateChips(states) {
        stateChipsContainer.innerHTML = "";
        selectedStates.clear();

        if (!states || states.length === 0) {
            controlsBar.style.display = "none";
            return;
        }

        controlsBar.style.display = "flex";

        states.forEach(st => {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = "state-chip";
            chip.textContent = st;

            if (st.includes("FORMACI") || states.length === 1) {
                chip.classList.add("active");
                selectedStates.add(st);
            }

            chip.addEventListener("click", () => {
                if (selectedStates.has(st)) {
                    if (selectedStates.size > 1) {
                        selectedStates.delete(st);
                        chip.classList.remove("active");
                    } else {
                        showToast("Debe mantener al menos un estado seleccionado", true);
                    }
                } else {
                    selectedStates.add(st);
                    chip.classList.add("active");
                }
            });

            stateChipsContainer.appendChild(chip);
        });
    }

    btnApplyFilters.addEventListener("click", async () => {
        if (!currentAnalysis) return;
        showToast("Recalculando avance de grupo...");

        const filter_estados = Array.from(selectedStates);
        const umbral_verde = parseFloat(inputUmbralVerde.value) || 80.0;
        const umbral_amarillo = parseFloat(inputUmbralAmarillo.value) || 50.0;

        try {
            const res = await apiFetch("/api/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    filter_estados,
                    umbral_verde,
                    umbral_amarillo
                })
            });

            const data = await res.json();
            if (!data.success) {
                throw new Error(data.error);
            }

            renderDashboard(data.analysis);
            showToast("Métricas y semáforo actualizados");
        } catch (err) {
            showToast(err.message, true);
        }
    });

    // -------------------------------------------------------------
    // EXPORTAR REPORTE EN EXCEL (CON TOKEN JWT)
    // -------------------------------------------------------------
    btnExportExcel.addEventListener("click", () => {
        const token = getToken();
        window.location.href = `/api/export?token=${encodeURIComponent(token || "")}`;
        showToast("Generando y descargando informe oficial en Excel...");
    });

    // -------------------------------------------------------------
    // RENDERIZADO DEL DASHBOARD
    // -------------------------------------------------------------
    function renderDashboard(analysis) {
        currentAnalysis = analysis;
        emptyState.style.display = "none";
        dashboardContent.style.display = "block";
        btnExportExcel.disabled = false;

        document.getElementById("meta-ficha").textContent = analysis.meta.ficha;
        document.getElementById("meta-programa").textContent = analysis.meta.programa;
        document.getElementById("meta-aprendices").textContent = `${analysis.meta.total_aprendices_analizados} Aprendices`;
        document.getElementById("meta-raps").textContent = `${analysis.meta.total_raps} RAPs`;

        const kpis = analysis.kpis;
        const pctAvance = kpis.porcentaje_avance_real;
        
        document.getElementById("kpi-avance-real").textContent = `${pctAvance}%`;
        document.getElementById("kpi-evaluaciones-detalle").textContent = 
            `${kpis.total_aprobados.toLocaleString()} / ${kpis.total_evaluaciones_posibles.toLocaleString()} juicios aprobados`;

        const gaugeCircle = document.getElementById("gauge-fill-circle");
        const gaugeText = document.getElementById("gauge-text");
        const circumference = 314.15;
        const offset = circumference - (pctAvance / 100) * circumference;
        gaugeCircle.style.strokeDashoffset = Math.max(0, offset);
        gaugeText.textContent = `${Math.round(pctAvance)}%`;

        document.getElementById("kpi-eficacia").textContent = `${kpis.porcentaje_aprobacion_evaluados}%`;
        document.getElementById("bar-eficacia").style.width = `${Math.min(100, kpis.porcentaje_aprobacion_evaluados)}%`;
        document.getElementById("kpi-eficacia-sub").textContent = 
            `${kpis.total_aprobados} Aprobados vs ${kpis.total_deficientes} Deficientes`;

        document.getElementById("kpi-cobertura").textContent = `${kpis.porcentaje_cobertura_evaluativa}%`;
        document.getElementById("bar-cobertura").style.width = `${Math.min(100, kpis.porcentaje_cobertura_evaluativa)}%`;
        document.getElementById("kpi-cobertura-sub").textContent = 
            `${(kpis.total_aprobados + kpis.total_deficientes)} con juicio emitido, ${kpis.total_por_evaluar} pendientes`;

        document.getElementById("count-raps-criticos").textContent = kpis.raps_criticos;
        document.getElementById("count-raps-avance").textContent = kpis.raps_en_avance;
        document.getElementById("count-raps-optimos").textContent = kpis.raps_optimos;

        document.getElementById("tab-count-raps").textContent = analysis.raps.length;
        document.getElementById("tab-count-apr").textContent = analysis.aprendices.length;

        renderRapsList(analysis.raps);
        renderAprendicesTable(analysis.aprendices);
        renderCompetenciasGrid(analysis.competencias);
        renderMatrix(analysis.matriz);
    }

    // -------------------------------------------------------------
    // PESTAÑA 1: LISTADO Y SEMÁFORO DE RAPS
    // -------------------------------------------------------------
    function renderRapsList(raps) {
        const container = document.getElementById("raps-list-container");
        container.innerHTML = "";

        const searchTerm = document.getElementById("search-rap").value.toLowerCase().trim();

        const filtered = raps.filter(r => {
            const matchesCategory = currentRapFilter === "all" || r.categoria_cod === currentRapFilter;
            const matchesSearch = !searchTerm || 
                r.rap.toLowerCase().includes(searchTerm) || 
                r.competencia.toLowerCase().includes(searchTerm) ||
                (r.instructor && r.instructor.toLowerCase().includes(searchTerm));
            return matchesCategory && matchesSearch;
        });

        if (filtered.length === 0) {
            container.innerHTML = `<div style="text-align:center; padding: 2rem; color: var(--text-muted);">No se encontraron RAPs que coincidan con los filtros.</div>`;
            return;
        }

        filtered.forEach(r => {
            const card = document.createElement("div");
            card.className = `rap-item-card ${r.categoria_cod}`;

            const fillClass = r.categoria_cod === "optimo" ? "fill-green" : (r.categoria_cod === "en_avance" ? "fill-amber" : "fill-red");
            const badgeClass = r.categoria_cod === "optimo" ? "status-optimo" : (r.categoria_cod === "en_avance" ? "status-avance" : "status-critico");

            card.innerHTML = `
                <div>
                    <div class="rap-comp-name">${escapeHtml(r.competencia)}</div>
                    <div class="rap-title">${escapeHtml(r.rap)}</div>
                    <div class="rap-instructor">👨‍🏫 Instructor: <strong>${escapeHtml(r.instructor || 'Por asignar')}</strong></div>
                </div>
                <div class="rap-progress-col">
                    <div class="rap-stats-header">
                        <span>Avance del Grupo</span>
                        <span>${r.porcentaje_aprobado}%</span>
                    </div>
                    <div class="kpi-progress-bar">
                        <div class="progress-fill ${fillClass}" style="width: ${r.porcentaje_aprobado}%"></div>
                    </div>
                    <div class="rap-stats-pills">
                        <span>🟢 ${r.aprobados} Aprobados</span>
                        <span>🔴 ${r.deficientes} Deficientes</span>
                        <span>⚪ ${r.pendientes} Pendientes</span>
                    </div>
                </div>
                <div class="rap-status-col">
                    <span class="status-badge ${badgeClass}">${r.semaforo}</span>
                    <span style="font-size: 0.75rem; color: var(--text-muted);">${r.aprobados} de ${r.aprobados + r.deficientes + r.pendientes} aprendices</span>
                </div>
            `;
            container.appendChild(card);
        });
    }

    document.getElementById("search-rap").addEventListener("input", () => {
        if (currentAnalysis) renderRapsList(currentAnalysis.raps);
    });

    document.querySelectorAll("#rap-status-filter .filter-chip").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("#rap-status-filter .filter-chip").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentRapFilter = btn.dataset.filter;
            if (currentAnalysis) renderRapsList(currentAnalysis.raps);
        });
    });

    // -------------------------------------------------------------
    // PESTAÑA 2: DIAGNÓSTICO POR APRENDIZ
    // -------------------------------------------------------------
    function renderAprendicesTable(aprendices) {
        const tbody = document.getElementById("tbody-aprendices");
        tbody.innerHTML = "";

        const searchTerm = document.getElementById("search-aprendiz").value.toLowerCase().trim();

        const filtered = aprendices.filter(a => {
            const matchesCategory = currentAprFilter === "all" || a.situacion_cod === currentAprFilter;
            const matchesSearch = !searchTerm ||
                a.nombre.toLowerCase().includes(searchTerm) ||
                a.documento.includes(searchTerm);
            return matchesCategory && matchesSearch;
        });

        if (filtered.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">No se encontraron aprendices con ese criterio de búsqueda.</td></tr>`;
            return;
        }

        filtered.forEach(a => {
            const tr = document.createElement("tr");

            const fillClass = a.situacion_cod === "al_dia" ? "fill-green" : (a.situacion_cod === "observacion" ? "fill-amber" : "fill-red");
            const badgeClass = a.situacion_cod === "al_dia" ? "status-optimo" : (a.situacion_cod === "observacion" ? "status-avance" : "status-critico");

            tr.innerHTML = `
                <td class="apr-name-col">${escapeHtml(a.nombre)}</td>
                <td>${escapeHtml(a.documento)}</td>
                <td><span style="font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; background: rgba(255,255,255,0.06);">${escapeHtml(a.estado_sofia)}</span></td>
                <td style="color: var(--color-green); font-weight: 600;">${a.raps_aprobados}</td>
                <td style="color: ${a.raps_deficientes > 0 ? 'var(--color-red)' : 'var(--text-muted)'}; font-weight: 600;">${a.raps_deficientes}</td>
                <td style="color: var(--text-muted);">${a.raps_pendientes}</td>
                <td>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <div class="kpi-progress-bar" style="width: 70px; margin-bottom: 0;">
                            <div class="progress-fill ${fillClass}" style="width: ${a.porcentaje_avance}%"></div>
                        </div>
                        <span style="font-weight: 600; font-size: 0.8rem;">${a.porcentaje_avance}%</span>
                    </div>
                </td>
                <td><span class="status-badge ${badgeClass}" style="display: inline-block;">${a.situacion}</span></td>
                <td>
                    <button class="btn-details" data-doc="${a.documento}">Ver Faltantes</button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll(".btn-details").forEach(btn => {
            btn.addEventListener("click", () => {
                const doc = btn.dataset.doc;
                const apr = currentAnalysis.aprendices.find(x => x.documento === doc);
                if (apr) openAprendizModal(apr);
            });
        });
    }

    document.getElementById("search-aprendiz").addEventListener("input", () => {
        if (currentAnalysis) renderAprendicesTable(currentAnalysis.aprendices);
    });

    document.querySelectorAll("#apr-status-filter .filter-chip").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("#apr-status-filter .filter-chip").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentAprFilter = btn.dataset.filter;
            if (currentAnalysis) renderAprendicesTable(currentAnalysis.aprendices);
        });
    });

    // Modal de Aprendiz
    function openAprendizModal(apr) {
        modalAprName.textContent = apr.nombre;
        modalAprDoc.textContent = `Documento: ${apr.documento}  |  Estado Sofía: ${apr.estado_sofia}  |  Avance: ${apr.porcentaje_avance}%`;

        let html = `
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1.5rem; text-align: center;">
                <div style="background: rgba(16, 185, 129, 0.1); padding: 0.75rem; border-radius: 8px; border: 1px solid rgba(16, 185, 129, 0.3);">
                    <div style="font-size: 1.35rem; font-weight: 700; color: var(--color-green);">${apr.raps_aprobados}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">RAPs Aprobados</div>
                </div>
                <div style="background: rgba(239, 68, 68, 0.1); padding: 0.75rem; border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.3);">
                    <div style="font-size: 1.35rem; font-weight: 700; color: var(--color-red);">${apr.raps_deficientes}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">RAPs Deficientes</div>
                </div>
                <div style="background: rgba(245, 158, 11, 0.1); padding: 0.75rem; border-radius: 8px; border: 1px solid rgba(245, 158, 11, 0.3);">
                    <div style="font-size: 1.35rem; font-weight: 700; color: var(--color-amber);">${apr.raps_pendientes}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">RAPs por Evaluar</div>
                </div>
            </div>
        `;

        if (apr.raps_deficientes_lista && apr.raps_deficientes_lista.length > 0) {
            html += `
                <div class="modal-section-title" style="color: var(--color-red);">⚠️ RAPs Deficientes (Urgente Concertar Plan de Mejoramiento)</div>
                <ul class="modal-raps-list">
                    ${apr.raps_deficientes_lista.map(r => `<li><strong>${escapeHtml(r)}</strong></li>`).join("")}
                </ul>
            `;
        } else {
            html += `<div style="color: var(--color-green); font-size: 0.85rem; margin-bottom: 1rem;">✅ No presenta ningún RAP calificado como Deficiente (D).</div>`;
        }

        if (apr.raps_pendientes_lista && apr.raps_pendientes_lista.length > 0) {
            html += `
                <div class="modal-section-title" style="color: var(--color-amber); margin-top: 1.5rem;">⏳ RAPs Aún Pendientes de Evaluación</div>
                <ul class="modal-raps-list pending">
                    ${apr.raps_pendientes_lista.map(r => `<li>${escapeHtml(r)}</li>`).join("")}
                </ul>
            `;
        }

        modalAprContent.innerHTML = html;
        modalBackdrop.style.display = "flex";
    }

    btnCloseModal.addEventListener("click", () => modalBackdrop.style.display = "none");
    modalBackdrop.addEventListener("click", (e) => {
        if (e.target === modalBackdrop) modalBackdrop.style.display = "none";
    });

    // -------------------------------------------------------------
    // PESTAÑA 3: DESGLOSE POR COMPETENCIA
    // -------------------------------------------------------------
    function renderCompetenciasGrid(competencias) {
        const container = document.getElementById("competencias-container");
        container.innerHTML = "";

        competencias.forEach(c => {
            const card = document.createElement("div");
            card.className = "comp-card glass-panel";

            const fillClass = c.porcentaje_avance >= 80 ? "fill-green" : (c.porcentaje_avance >= 50 ? "fill-amber" : "fill-red");
            const statusClass = c.porcentaje_avance >= 80 ? "status-optimo" : (c.porcentaje_avance >= 50 ? "status-avance" : "status-critico");

            card.innerHTML = `
                <div>
                    <div class="comp-header">
                        <h4 class="comp-title">${escapeHtml(c.competencia)}</h4>
                        <span class="status-badge ${statusClass}">${c.estado}</span>
                    </div>
                </div>
                <div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.4rem;">
                        <span>Avance Global</span>
                        <span>${c.porcentaje_avance}%</span>
                    </div>
                    <div class="kpi-progress-bar">
                        <div class="progress-fill ${fillClass}" style="width: ${c.porcentaje_avance}%"></div>
                    </div>
                </div>
                <div class="comp-stats-grid">
                    <div>
                        <div class="comp-stat-num">${c.total_raps}</div>
                        <div class="comp-stat-lbl">Total RAPs</div>
                    </div>
                    <div>
                        <div class="comp-stat-num" style="color: var(--color-green);">${c.aprobados}</div>
                        <div class="comp-stat-lbl">Aprobaciones</div>
                    </div>
                    <div>
                        <div class="comp-stat-num" style="color: ${c.deficientes > 0 ? 'var(--color-red)' : 'var(--text-muted)'};">${c.deficientes}</div>
                        <div class="comp-stat-lbl">Deficientes</div>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    }

    // -------------------------------------------------------------
    // PESTAÑA 4: MATRIZ APRENDIZ X RAP
    // -------------------------------------------------------------
    function renderMatrix(matriz) {
        const thead = document.getElementById("thead-matrix");
        const tbody = document.getElementById("tbody-matrix");

        let headerHtml = `<tr><th>Documento</th><th>Nombre Aprendiz</th>`;
        matriz.raps.forEach((rap, idx) => {
            headerHtml += `<th title="${escapeHtml(rap)}">RAP ${idx + 1}</th>`;
        });
        headerHtml += `</tr>`;
        thead.innerHTML = headerHtml;

        let bodyHtml = "";
        matriz.filas.forEach(f => {
            bodyHtml += `<tr>`;
            bodyHtml += `<td>${escapeHtml(f.documento)}</td>`;
            bodyHtml += `<td class="apr-name-col">${escapeHtml(f.nombre)}</td>`;

            matriz.raps.forEach(rap => {
                const j = f.juicios[rap] || "P";
                const badgeClass = j === "A" ? "badge-a" : (j === "D" ? "badge-d" : "badge-p");
                bodyHtml += `<td><span class="${badgeClass}" title="${escapeHtml(rap)}: ${j}">${j}</span></td>`;
            });
            bodyHtml += `</tr>`;
        });
        tbody.innerHTML = bodyHtml;
    }

    // -------------------------------------------------------------
    // PESTAÑA 5: HISTÓRICO DE CORTES Y LIQUIBASE
    // -------------------------------------------------------------
    async function loadHistoryData() {
        try {
            const res = await apiFetch("/api/history");
            const data = await res.json();
            if (!data.success) return;

            document.getElementById("tab-count-hist").textContent = data.items.length;

            // 1. Renderizar estado Liquibase
            const lb = data.liquibase;
            const lbBadge = document.getElementById("liquibase-badge");
            if (lb && lb.up_to_date) {
                lbBadge.className = "status-badge status-optimo";
                lbBadge.textContent = `🟢 Liquibase Al Día (${lb.executed_count} changesets aplicados)`;
            } else if (lb) {
                lbBadge.className = "status-badge status-avance";
                lbBadge.textContent = `🟡 Liquibase (${lb.pending_count} pendientes)`;
            }

            const tbodyLb = document.getElementById("tbody-liquibase");
            tbodyLb.innerHTML = "";
            if (lb && lb.executed) {
                lb.executed.forEach(cs => {
                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td style="font-weight: 700;">#${cs.ORDEREXECUTED}</td>
                        <td style="font-family: monospace; color: #38BDF8;">${escapeHtml(cs.ID)}</td>
                        <td>${escapeHtml(cs.AUTHOR)}</td>
                        <td style="font-size: 0.78rem; color: var(--text-muted);">${escapeHtml(cs.FILENAME)}</td>
                        <td><span style="font-size: 0.72rem; padding: 0.15rem 0.45rem; border-radius: 4px; background: rgba(57,169,0,0.15); color: #4ADE80;">${escapeHtml(cs.LABELS || 'v1.0')}</span></td>
                        <td style="font-size: 0.8rem;">${escapeHtml(cs.COMMENTS || '-')}</td>
                        <td style="font-family: monospace; font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(cs.MD5SUM)}</td>
                        <td style="font-size: 0.78rem;">${escapeHtml(cs.DATEEXECUTED)}</td>
                        <td><span class="status-badge status-optimo">${escapeHtml(cs.EXECTYPE)}</span></td>
                    `;
                    tbodyLb.appendChild(tr);
                });
            }

            // 2. Renderizar tabla de cortes históricos
            const tbodyHist = document.getElementById("tbody-historico");
            tbodyHist.innerHTML = "";
            if (!data.items || data.items.length === 0) {
                tbodyHist.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">No hay cortes históricos registrados aún.</td></tr>`;
            } else {
                data.items.forEach(item => {
                    const tr = document.createElement("tr");
                    const delta = item.delta_avance || 0;
                    const deltaStr = delta > 0 ? `+${delta}% ▲` : (delta < 0 ? `${delta}% ▼` : `0.0% ▬`);
                    const deltaColor = delta > 0 ? "var(--color-green)" : (delta < 0 ? "var(--color-red)" : "var(--text-muted)");

                    tr.innerHTML = `
                        <td style="font-weight: 700;">#${item.id}</td>
                        <td style="font-size: 0.8rem;">${escapeHtml(item.fecha_analisis)}</td>
                        <td><strong>${escapeHtml(item.ficha_codigo)}</strong></td>
                        <td style="font-size: 0.8rem;">${escapeHtml(item.archivo_origen)}</td>
                        <td>${item.total_aprendices_analizados}</td>
                        <td style="font-weight: 700; color: var(--color-green);">${item.pct_avance_real}%</td>
                        <td style="font-weight: 600; color: ${deltaColor};">${deltaStr}</td>
                        <td>${item.cambios_juicios_count > 0 ? `<span class="status-badge status-avance">${item.cambios_juicios_count} cambios</span>` : `<span style="color: var(--text-muted); font-size: 0.78rem;">Sin cambios</span>`}</td>
                        <td style="font-size: 0.8rem; color: var(--text-secondary);">${escapeHtml(item.observaciones || '-')}</td>
                        <td>
                            <div style="display: flex; gap: 0.4rem;">
                                <button class="btn-details btn-load-snap" data-id="${item.id}">Cargar</button>
                                ${can("historico.eliminar") ? `<button class="btn-details btn-del-snap" data-id="${item.id}" style="border-color: rgba(239,68,68,0.4); color: #F87171;">✕</button>` : ""}
                            </div>
                        </td>
                    `;
                    tbodyHist.appendChild(tr);
                });

                tbodyHist.querySelectorAll(".btn-load-snap").forEach(btn => {
                    btn.addEventListener("click", async () => {
                        const id = btn.dataset.id;
                        try {
                            const r = await apiFetch(`/api/history/${id}`);
                            const snapData = await r.json();
                            if (!snapData.success) throw new Error(snapData.error);
                            renderDashboard(snapData.analysis);
                            fileNameText.textContent = `Corte Histórico #${id} - ${snapData.snapshot.archivo_origen} (${snapData.snapshot.fecha_analisis})`;
                            fileInfo.style.display = "inline-flex";
                            showToast(`Corte histórico #${id} restaurado en pantalla`);
                        } catch (e) {
                            showToast(e.message, true);
                        }
                    });
                });

                tbodyHist.querySelectorAll(".btn-del-snap").forEach(btn => {
                    btn.addEventListener("click", async () => {
                        const id = btn.dataset.id;
                        try {
                            const r = await apiFetch("/api/history/delete", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ id: parseInt(id, 10) })
                            });
                            const resDel = await r.json();
                            if (resDel.success) {
                                await loadHistoryData();
                                showToast(`Corte #${id} eliminado del histórico`);
                            }
                        } catch (e) {
                            showToast(e.message, true);
                        }
                    });
                });
            }

            // 3. Renderizar cambios de juicio recientes si existen
            const changesSection = document.getElementById("juicio-changes-section");
            const tbodyChanges = document.getElementById("tbody-cambios-juicios");
            tbodyChanges.innerHTML = "";
            if (data.recent_juicio_changes && data.recent_juicio_changes.length > 0) {
                changesSection.style.display = "block";
                data.recent_juicio_changes.forEach(ch => {
                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td>#${ch.analisis_id}</td>
                        <td>${escapeHtml(ch.ficha_codigo)}</td>
                        <td>${escapeHtml(ch.documento)}</td>
                        <td class="apr-name-col">${escapeHtml(ch.nombre_aprendiz)}</td>
                        <td style="font-size: 0.78rem;">${escapeHtml(ch.rap)}</td>
                        <td>
                            <span class="badge-${ch.juicio_anterior.toLowerCase()}">${escapeHtml(ch.juicio_anterior)}</span>
                            ➔
                            <span class="badge-${ch.juicio_nuevo.toLowerCase()}">${escapeHtml(ch.juicio_nuevo)}</span>
                        </td>
                        <td style="font-size: 0.78rem; color: var(--text-muted);">${escapeHtml(ch.fecha_deteccion)}</td>
                    `;
                    tbodyChanges.appendChild(tr);
                });
            } else {
                changesSection.style.display = "none";
            }
        } catch (err) {
            console.error("Error cargando histórico:", err);
        }
    }

    if (btnSaveSnapshot) {
        btnSaveSnapshot.addEventListener("click", async () => {
            if (!currentAnalysis) return;
            const obs = inputHistObs.value.trim() || "Corte guardado manualmente por el instructor";
            try {
                const res = await apiFetch("/api/history/save", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ observaciones: obs })
                });
                const data = await res.json();
                if (!data.success) throw new Error(data.error);
                inputHistObs.value = "";
                await loadHistoryData();
                showToast(`Corte #${data.history_record.analisis_id} guardado en SQLite exitosamente`);
            } catch (err) {
                showToast(err.message, true);
            }
        });
    }

    // -------------------------------------------------------------
    // PESTAÑA 6: REGISTROS EXCEL ALMACENADOS
    // -------------------------------------------------------------
    function fillSelect(selectId, values, allLabel, labelFn) {
        const sel = document.getElementById(selectId);
        const current = sel.value;
        sel.innerHTML = `<option value="">${allLabel}</option>` +
            values.map(v => {
                const val = typeof v === "object" ? v.value : v;
                const lbl = labelFn ? labelFn(v) : val;
                return `<option value="${escapeHtml(val)}">${escapeHtml(lbl)}</option>`;
            }).join("");
        sel.value = current;
    }

    async function loadCargas() {
        if (!can("registros.ver")) return;
        try {
            const res = await apiFetch("/api/registros/cargas");
            const data = await res.json();
            if (!data.success) return;

            document.getElementById("tab-count-reg").textContent = data.total_registros.toLocaleString();
            fillSelect("reg-f-ficha", data.fichas, "Todas las fichas");
            fillSelect("reg-f-estado", data.estados, "Todos los estados");
            fillSelect("reg-f-carga", data.cargas.map(c => ({ value: String(c.id), c })), "Todas las cargas",
                v => `#${v.c.id} - ${v.c.nombre_archivo} (${v.c.fecha_carga})`);

            const tbody = document.getElementById("tbody-cargas");
            if (!data.cargas.length) {
                tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:1.5rem; color: var(--text-muted);">Aún no hay archivos almacenados.</td></tr>`;
                return;
            }
            tbody.innerHTML = data.cargas.map(c => `
                <tr>
                    <td style="font-weight:700;">#${c.id}</td>
                    <td style="font-size:0.8rem;">${escapeHtml(c.fecha_carga)}</td>
                    <td style="font-size:0.8rem;">${escapeHtml(c.nombre_archivo)}</td>
                    <td>${escapeHtml(c.ficha_codigo || "-")}</td>
                    <td>${c.total_filas.toLocaleString()}</td>
                    <td>${escapeHtml(c.username)}</td>
                    <td class="hash-short" title="${escapeHtml(c.hash_sha256)}">${escapeHtml(c.hash_sha256.slice(0, 16))}…</td>
                    <td>
                        <div style="display:flex; gap:0.4rem;">
                            <button class="btn-details btn-carga-filtrar" data-id="${c.id}">Ver filas</button>
                            <button class="btn-details btn-carga-verificar" data-id="${c.id}">🛡️ Integridad</button>
                            ${can("registros.eliminar") ? `<button class="btn-details btn-carga-eliminar" data-id="${c.id}" style="border-color: rgba(239,68,68,0.4); color: #F87171;">✕</button>` : ""}
                        </div>
                    </td>
                </tr>
            `).join("");

            tbody.querySelectorAll(".btn-carga-filtrar").forEach(btn => btn.addEventListener("click", () => {
                document.getElementById("reg-f-carga").value = btn.dataset.id;
                loadRegistros(1);
            }));

            tbody.querySelectorAll(".btn-carga-verificar").forEach(btn => btn.addEventListener("click", async () => {
                try {
                    const r = await apiFetch(`/api/registros/cargas/${btn.dataset.id}/integridad`);
                    const v = await r.json();
                    if (!v.success) throw new Error(v.error);
                    if (v.integro) {
                        showToast(`✅ Carga #${v.carga_id} íntegra: ${v.total_encontrado} filas verificadas con SHA-256`);
                    } else {
                        showToast(`⚠️ Carga #${v.carga_id}: ${v.registros_alterados.length} filas alteradas, ${v.filas_faltantes} faltantes`, true);
                    }
                } catch (e) {
                    showToast(e.message, true);
                }
            }));

            tbody.querySelectorAll(".btn-carga-eliminar").forEach(btn => btn.addEventListener("click", async () => {
                if (!confirm(`¿Eliminar la carga #${btn.dataset.id} y todos sus registros? Esta acción queda registrada en la bitácora.`)) return;
                try {
                    const r = await apiFetch("/api/registros/cargas/delete", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ id: parseInt(btn.dataset.id, 10) })
                    });
                    const d = await r.json();
                    if (d.success) {
                        showToast(`Carga #${btn.dataset.id} eliminada`);
                        await loadCargas();
                        loadRegistros(1);
                    }
                } catch (e) {
                    showToast(e.message, true);
                }
            }));
        } catch (err) {
            console.error("Error cargando cargas:", err);
        }
    }

    async function loadRegistros(page = 1) {
        if (!can("registros.ver")) return;
        const params = new URLSearchParams({ page: String(page), page_size: "50" });
        const map = {
            carga_id: "reg-f-carga", ficha: "reg-f-ficha", estado: "reg-f-estado", juicio: "reg-f-juicio",
            documento: "reg-f-documento", rap: "reg-f-rap", q: "reg-f-q"
        };
        Object.entries(map).forEach(([k, id]) => {
            const v = document.getElementById(id).value.trim();
            if (v) params.set(k, v);
        });

        try {
            const res = await apiFetch(`/api/registros?${params.toString()}`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);

            regPage = data.page;
            regPages = data.pages;
            document.getElementById("reg-sum-total").textContent = data.total.toLocaleString();
            document.getElementById("reg-sum-apr").textContent = data.aprendices_distintos.toLocaleString();
            document.getElementById("reg-sum-a").textContent = data.resumen_juicios.A.toLocaleString();
            document.getElementById("reg-sum-d").textContent = data.resumen_juicios.D.toLocaleString();
            document.getElementById("reg-sum-p").textContent = data.resumen_juicios.P.toLocaleString();
            document.getElementById("reg-page-info").textContent = `Página ${data.page} de ${data.pages}`;
            document.getElementById("btn-reg-prev").disabled = data.page <= 1;
            document.getElementById("btn-reg-next").disabled = data.page >= data.pages;

            const tbody = document.getElementById("tbody-registros");
            if (!data.items.length) {
                tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:1.5rem; color: var(--text-muted);">No hay registros que coincidan con los filtros.</td></tr>`;
                return;
            }
            tbody.innerHTML = data.items.map(r => {
                const j = r.juicio_normalizado;
                const badge = j === "A" ? "badge-a" : (j === "D" ? "badge-d" : "badge-p");
                return `
                    <tr>
                        <td style="font-size:0.78rem;">#${r.carga_id} / ${r.fila_numero}</td>
                        <td>${escapeHtml(r.ficha_codigo || "-")}</td>
                        <td>${escapeHtml(r.documento || "-")}</td>
                        <td class="apr-name-col">${escapeHtml(r.nombre_aprendiz || "-")}</td>
                        <td style="font-size:0.75rem;">${escapeHtml(r.estado_aprendiz || "-")}</td>
                        <td style="font-size:0.75rem; max-width:220px;">${escapeHtml(r.competencia || "-")}</td>
                        <td style="font-size:0.75rem; max-width:280px;">${escapeHtml(r.rap || "-")}</td>
                        <td><span class="${badge}" title="Original: ${escapeHtml(r.juicio_original || "vacío")}">${j}</span></td>
                        <td style="font-size:0.75rem;">${escapeHtml(r.fecha_juicio || "-")}</td>
                        <td style="font-size:0.75rem;">${escapeHtml(r.instructor || "-")}</td>
                        <td><button class="btn-details btn-reg-detalle" data-id="${r.id}">Fila original</button></td>
                    </tr>
                `;
            }).join("");

            tbody.querySelectorAll(".btn-reg-detalle").forEach(btn => btn.addEventListener("click", () => openRegistroModal(btn.dataset.id)));
        } catch (err) {
            showToast(err.message, true);
        }
    }

    async function openRegistroModal(id) {
        try {
            const res = await apiFetch(`/api/registros/${id}`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            const r = data.registro;
            modalAprName.textContent = `Registro #${r.id} — Carga #${r.carga_id}, fila ${r.fila_numero}`;
            modalAprDoc.textContent = `${r.nombre_aprendiz || "-"} | Doc: ${r.documento || "-"} | Integridad: ${r.integridad_ok ? "✅ Verificada (SHA-256)" : "⚠️ ALTERADA"}`;
            const rows = Object.entries(r.datos_originales).map(([k, v]) =>
                `<tr><td style="font-weight:600; color: var(--text-secondary);">${escapeHtml(k)}</td><td>${escapeHtml(v === null ? "" : v)}</td></tr>`
            ).join("");
            modalAprContent.innerHTML = `
                <div class="modal-section-title" style="margin-top:0;">Columnas originales del Excel</div>
                <div class="table-responsive"><table class="data-table"><tbody>${rows}</tbody></table></div>
                <div class="modal-section-title">Hash de integridad de la fila</div>
                <div class="jwt-code-block">${escapeHtml(r.hash_fila)}</div>
            `;
            modalBackdrop.style.display = "flex";
        } catch (e) {
            showToast(e.message, true);
        }
    }

    document.getElementById("btn-reg-buscar").addEventListener("click", () => loadRegistros(1));
    document.getElementById("btn-reg-limpiar").addEventListener("click", () => {
        ["reg-f-carga", "reg-f-ficha", "reg-f-estado", "reg-f-juicio", "reg-f-documento", "reg-f-rap", "reg-f-q"]
            .forEach(id => document.getElementById(id).value = "");
        loadRegistros(1);
    });
    document.getElementById("btn-reg-prev").addEventListener("click", () => { if (regPage > 1) loadRegistros(regPage - 1); });
    document.getElementById("btn-reg-next").addEventListener("click", () => { if (regPage < regPages) loadRegistros(regPage + 1); });
    ["reg-f-documento", "reg-f-rap", "reg-f-q"].forEach(id => {
        document.getElementById(id).addEventListener("keydown", e => { if (e.key === "Enter") loadRegistros(1); });
    });

    // -------------------------------------------------------------
    // PESTAÑA 7: SEGURIDAD Y AUDITORÍA
    // -------------------------------------------------------------
    async function loadAuditoria() {
        if (!can("auditoria.ver")) return;
        const evento = document.getElementById("aud-f-evento").value;
        const params = new URLSearchParams({ limit: "200" });
        if (evento) params.set("evento", evento);
        try {
            const res = await apiFetch(`/api/seguridad/auditoria?${params.toString()}`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);

            const badge = document.getElementById("chain-badge");
            if (data.cadena.valid) {
                badge.className = "status-badge status-optimo";
                badge.textContent = `🟢 Cadena de auditoría íntegra (${data.cadena.total_eventos} eventos verificados)`;
            } else {
                badge.className = "status-badge status-critico";
                badge.textContent = `🔴 Cadena ROTA en evento #${data.cadena.evento_roto_id}: ${data.cadena.motivo}`;
            }

            const rbac = data.rbac;
            const roles = rbac.roles.map(r => r.codigo);
            let html = `<thead><tr><th>Permiso</th><th>Descripción</th>${roles.map(r => `<th style="text-align:center;">${escapeHtml(r)}</th>`).join("")}</tr></thead><tbody>`;
            rbac.permisos.forEach(p => {
                html += `<tr><td style="font-family:monospace; color:#38BDF8;">${escapeHtml(p.codigo)}</td><td style="font-size:0.8rem;">${escapeHtml(p.descripcion)}</td>`;
                roles.forEach(r => {
                    const ok = (rbac.matriz[r] || []).includes(p.codigo);
                    html += `<td class="${ok ? "rbac-yes" : "rbac-no"}">${ok ? "✔" : "—"}</td>`;
                });
                html += `</tr>`;
            });
            document.getElementById("table-rbac").innerHTML = html + "</tbody>";

            const tbody = document.getElementById("tbody-auditoria");
            tbody.innerHTML = data.eventos.map(ev => {
                const cls = ev.resultado === "OK" ? "status-optimo" : (ev.resultado === "DENEGADO" || ev.resultado === "ERROR" ? "status-critico" : "status-avance");
                return `
                    <tr title="${escapeHtml(ev.detalle_json)}">
                        <td>${ev.id}</td>
                        <td style="font-size:0.78rem;">${escapeHtml(ev.fecha)}</td>
                        <td style="font-family:monospace; font-size:0.78rem;">${escapeHtml(ev.evento)}</td>
                        <td>${escapeHtml(ev.username)}</td>
                        <td style="font-size:0.75rem;">${escapeHtml(ev.rol || "-")}</td>
                        <td style="font-size:0.75rem;">${escapeHtml(ev.recurso || "-")}</td>
                        <td><span class="status-badge ${cls}">${escapeHtml(ev.resultado)}</span></td>
                        <td style="font-size:0.75rem;">${escapeHtml(ev.ip_origen || "-")}</td>
                        <td class="hash-short" title="${escapeHtml(ev.hash_evento)}">${escapeHtml(ev.hash_evento.slice(0, 12))}…</td>
                    </tr>
                `;
            }).join("") || `<tr><td colspan="9" style="text-align:center; padding:1.5rem; color: var(--text-muted);">Sin eventos.</td></tr>`;
        } catch (err) {
            showToast(err.message, true);
        }
    }

    document.getElementById("btn-aud-refresh").addEventListener("click", loadAuditoria);
    document.getElementById("aud-f-evento").addEventListener("change", loadAuditoria);

    // -------------------------------------------------------------
    // CONTROL DE PESTAÑAS (TABS)
    // -------------------------------------------------------------
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));

            btn.classList.add("active");
            const tabId = btn.dataset.tab;
            const targetContent = document.getElementById(tabId);
            if (targetContent) targetContent.classList.add("active");

            if (tabId === "tab-historico") {
                loadHistoryData();
            } else if (tabId === "tab-registros") {
                loadCargas();
                loadRegistros(1);
            } else if (tabId === "tab-seguridad") {
                loadAuditoria();
            }
        });
    });

    function escapeHtml(text) {
        if (!text) return "";
        return text.toString()
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Verificar autenticación JWT al iniciar la aplicación
    checkInitialAuth();
});
